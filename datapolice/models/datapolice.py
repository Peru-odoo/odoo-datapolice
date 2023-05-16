from odoo import models, fields, api, _
import json
import base64
from datetime import datetime
from odoo.exceptions import UserError, RedirectWarning, ValidationError
import logging

_logger = logging.getLogger("datapolice")


class DataPolice(models.Model):
    _name = "data.police"

    active = fields.Boolean(default=True)
    name = fields.Char("Name", required=True, translate=True)
    fetch_expr = fields.Text(
        "Fetch Expr",
        help="If given then used; return records, otherwise domain is used with model",
    )
    check_expr = fields.Text(
        "Expression to chec",
        required=False,
        help="Input: obj/object - return False for error, return None/True for ok, or raise Exception or return a string",
    )
    fix_expr = fields.Char("Def to fix error", required=False)
    model_id = fields.Many2one(
        "ir.model", string="Model", required=True, ondelete="cascade"
    )
    enabled = fields.Boolean("Enabled", default=True)
    errors = fields.Integer("Count Errors")
    domain = fields.Text("Domain")
    recipients = fields.Char("Mail-Recipients", size=1024)
    user_ids = fields.Many2many("res.users", string="Recipients (users)")
    inform_current_user_immediately = fields.Boolean(
        "Inform current user immediately", default=False
    )
    last_errors = fields.Text("Last Error Log")
    cronjob_group_id = fields.Many2one(
        "datapolice.cronjob.group", string="Cronjob Group"
    )
    trigger_ids = fields.One2many(
        "datapolice.trigger", "datapolice_id", ondelete="cascade"
    )

    def toggle_active(self):
        self.active = not self.active

    @api.constrains("src_model", "domain", "checkdef", "expr")
    def check_model_domain(self):
        for rec in self:
            if rec.domain and rec.src_model:
                raise ValidationError("Either provide src_model OR domain")
            if not rec.checkdef and not rec.expr:
                raise ValidationError("Either provide expression or check-function")

    @api.model
    def create(self, values):
        if "def" in values.keys():
            raise Exception("Please use checkdef instead of def!!!")
        result = super(DataPolice, self).create(values)
        return result

    @api.constrains("recipients")
    def _check_recipients(self):
        for rec in self:
            recps = rec.recipients or ""
            recps = recps.replace(";", ",")

            def convert(x):
                x = x.strip()
                return x

            recps = list(map(convert, recps.split(",")))
            recps = ",".join(recps)
            if recps != (rec.recipients or ""):
                rec.recipients = recps

    @api.model
    def _exec_get_result(self, code, globals_dict):
        code = code.strip()
        code = code.splitlines()
        if code and code[-1].startswith(" ") or code[-1].startswith("\t"):
            code.append("True")
        code[-1] = "return " + code[-1]
        code = "\n".join(["  " + x for x in code])
        wrapper = "def __wrap():\n" f"{code}\n\n" "result_dict['result'] = __wrap()"
        result_dict = {}
        globals_dict["result_dict"] = result_dict
        exec(wrapper, globals_dict)
        return result_dict.get("result")

    def _fetch_objects(self):
        self.ensure_one()
        obj = self.env[self.model_id.model]
        if self.domain:
            instances = obj.search(self.domain)
        else:
            instances = self._exec_get_result(
                self.fetch_expr, {"model": obj, "obj": obj}
            )
        instances = instances.with_context(prefetch_fields=False)

    def _run_code(self, instance, expr):
        exception = ""
        try:
            result = self._exec_get_result(expr, {"obj": instance})
            if result is None or result is True:
                result = True
            else:
                if isinstance(result, str):
                    exception = result
                result = False
        except Exception as e:
            exception = str(e)
            result = False

        return {
            "ok": result,
            "exception": exception,
        }

    def _make_checks(self, instances):
        for idx, obj in enumerate(instances, 1):
            _logger.debug(f"Checking {self.name} {idx} of {len(instances)}")
            instance_name = self.env["data.police.formatter"].do_format(obj)
            res = self._run_code(obj, self.check_expr)
            res["tried_to_fix"] = False

            def pushup(text):
                if not res['ok']:
                    yield {
                        "model": obj._name,
                        "res_id": obj.id,
                        "text": text,
                    }

            if not res["ok"] and self.fix_expr:
                res_fix = self.with_context(datapolice_run_fixdef=True)._run_code(obj, self.fix_expr)
                res["tried_to_fix"] = True
                res["fix_result"] = res_fix

                if not res["ok"] and (
                    not res["tried_to_fix"] or not res["fix_result"]["ok"]
                ):
                    text = "; ".join(
                        filter(
                            bool,
                            [
                                instance_name,
                                res.get("exception", ""),
                                res.get("fix_result", {}).get("exception"),
                            ],
                        )
                    )
                    _logger.error(
                        f"Data Police {self.name}: not ok at {obj._name} {obj.id} {text}"
                    )
                    yield from pushup(text)
                    self.env.cr.commit()

            elif not res['ok']:
                yield from pushup(res['exception'])

    def run_single_instance(self, instance):
        self.ensure_one()
        errors = list(self._make_checks(instance))
        return errors

    def run(self):
        for police in self:
            errors = []

            instances_to_check = police._fetch_objects()
            errors = list(police._make_checks(instances_to_check))
            police.errors = len(errors)
            police.last_errors = json.dumps(errors, indent=4)
            self.env.cr.commit()

    def _get_all_email_recipients(self):
        def str2mails(s):
            s = s or ""
            s = s.replace(",", ";")
            return [x.lower() for x in s.split(";") if x]

        dp_recipients = []
        for dp in self:
            if dp.recipients:
                dp_recipients += str2mails(dp.recipients)
            if dp.user_ids:
                dp_recipients += [x.lower() for x in dp.user_ids.mapped("email") if x]

        mail_to = ",".join(set(dp_recipients))

        return mail_to

    def _get_error_text(self):
        self.ensure_one()
        errors = json.loads(self.last_errors)
        if not errors:
            name = "Success: #{self.name}"
            return name, name
        text = f"<h2>{self.name}</h2><ul>"
        small_text = text
        for i, error in enumerate(
            sorted(
                errors,
                key=lambda e: (e.get("model", False), e.get("res_id", False)),
                reverse=True,
            )
        ):
            if "model" in error and "res_id" in error:
                url = self.env["ir.config_parameter"].get_param("web.base.url")
                url += "#model=" + error["model"] + "&id=" + str(error["res_id"])
                link = "<a href='{}'>{}</a>".format(url, error["text"])
                appendix = "<li>{}</li>\n".format(link)
            else:
                appendix = "<li>{}</li>\n".format(error)
            text += appendix
            if i < 50:
                small_text += appendix

        text += "</ul>"
        small_text += "</ul>"
        return small_text, text

    def _send_mail_for_single_instance(self, instance, errors):
        mail_to = self._get_all_email_recipients()
        new_small_text, new_text = self._get_error_text()
        by_email = {}
        for email in mail_to.split(","):
            by_email.setdefault(email, {"text": "", "small_text": ""})
            by_email[email]["text"] = new_text
            by_email[email]["small_text"] = new_small_text
        subject = f"DataPolice: {instance.name_get()[0][1]}"
        self._send_mail_technically(by_email, subject=subject)

    def _send_mails(self):
        by_email = {}
        for dp in self:
            mail_to = dp._get_all_email_recipients()
            new_small_text, new_text = self._get_error_text()

            for email in mail_to.split(","):
                by_email.setdefault(email, {"text": "", "small_text": ""})
                by_email[email]["text"] += new_text
                by_email[email]["small_text"] += new_small_text
        self._send_mail_technically(by_email)

    def _send_mail_technically(self, by_email, subject=None):

        for email, texts in by_email.items():
            if not texts["text"]:
                continue
            text = base64.encodestring(texts["text"].encode("utf-8"))
            self.env["mail.mail"].create(
                {
                    "auto_delete": True,
                    "subject": subject or f"DataPolice Run {datetime.now()}",
                    "body_html": texts["small_text"],
                    "body": texts["small_text"],
                    "email_to": email,
                    "attachment_ids": [
                        [
                            0,
                            0,
                            {
                                "datas": text,
                                "datas_fname": "data_police.html",
                                "name": "data_police.html",
                            },
                        ]
                    ],
                }
            ).send()

    def show_errors(self):
        errors = json.loads(self.last_errors)
        ids = [x["res_id"] for x in errors if "res_id" in x]

        return {
            "name": f"Errors of {self.name}",
            "view_type": "form",
            "res_model": self._name,
            "domain": [("id", "in", ids)],
            "views": [(False, "tree"), (False, "form")],
            "type": "ir.actions.act_window",
            "target": "current",
        }
