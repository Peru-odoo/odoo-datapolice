from odoo import models, fields, api, _
import uuid
import arrow
import json
import base64
from datetime import datetime
from odoo.exceptions import UserError, RedirectWarning, ValidationError
import logging
from datetime import datetime, date, timedelta
from contextlib import contextmanager
from odoo.tools import table_exists
from odoo.tools.safe_eval import safe_eval
from odoo import registry

try:
    from odoo.addons.queue_job.exception import RetryableJobError
except:

    class RetryableJobError(Exception):
        def __init__(self, *arsg, **kw):
            super().__init__(*args, **kw)


_logger = logging.getLogger("datapolice")


class DataPolice(models.Model):
    _inherit = "mail.thread"
    _name = "data.police"

    active = fields.Boolean(default=True)
    tag_ids = fields.Many2many("datapolice.tag", string="Tags")
    group_id = fields.Many2one("datapolice.group", string="Group")
    limit = fields.Integer("Limit")
    fix_counter = fields.Integer("Fix Counter", compute="_compute_increment")
    name = fields.Char("Name", required=True, translate=True)
    responsible_id = fields.Many2one("res.users", string="Responsible")
    fetch_expr = fields.Text(
        "Fetch Expr",
        help="If given then used; return records, otherwise domain is used with model",
    )
    check_expr = fields.Text(
        "Expression to chec",
        required=False,
        help="Input: obj/object - return False for error, return None/True for ok, or raise Exception or return a string",
    )
    date_field_id = fields.Many2one(
        "ir.model.fields",
        "Date Field",
        help="To put errors into the correct time period, this field is required.",
    )
    fix_expr = fields.Char("Def to fix error", required=False)
    model_id = fields.Many2one(
        "ir.model", string="Model", required=True, ondelete="cascade"
    )
    enabled = fields.Boolean("Enabled", default=True, tracking=True)
    errors = fields.Integer("Count Errors", compute="_compute_count_errors", store=True)
    checked = fields.Integer("Count Checked", compute="_compute_increment")
    ratio = fields.Float("Success Ratio [%]", compute="_compute_success")
    domain = fields.Text("Domain")
    recipients = fields.Char("Mail-Recipients", size=1024)
    user_ids = fields.Many2many("res.users", string="Recipients (users)")
    inform_current_user_immediately = fields.Boolean(
        "Inform current user immediately (Needs write trigger to be defined)",
        default=False,
    )
    cronjob_group_id = fields.Many2one(
        "datapolice.cronjob.group", string="Cronjob Group"
    )
    trigger_ids = fields.One2many(
        "datapolice.trigger", "datapolice_id", ondelete="cascade", copy=True
    )
    field_trigger_ids = fields.One2many(
        "datapolice.trigger_field", "datapolice_id", ondelete="cascade", copy=True
    )

    make_activity = fields.Boolean("Make Activity")
    activity_type_id = fields.Many2one("mail.activity.type", string="Activity Type")
    activity_deadline_days = fields.Integer("Activity Deadline Days")
    activity_summary = fields.Char("Activity Summary")
    activity_user_id = fields.Many2one("res.users", string="Assign Activity User")
    activity_user_from_context = fields.Boolean("User from context")
    acknowledge_ids = fields.One2many("datapolice.ack", "datapolice_id")
    lasterror_ids = fields.One2many("datapolice.lasterror", "datapolice_id")
    queuejob_channel = fields.Char("Queuejob Channel", default="root")
    queuejob_priority = fields.Integer("Queuejob Priority", default=10)
    queuejob_enabled = fields.Boolean("Use queuejobs")

    def del_all_errors(self):
        self.acknowledge_ids.sudo().unlink()
        self.lasterror_ids.sudo().unlink()
        return True

    def _make_activity(self, instance):
        dt = arrow.utcnow().shift(days=self.activity_deadline_days).datetime
        instance_model = (
            self.env["ir.model"].sudo().search([("model", "=", instance._name)])
        )
        data = {
            "activity_type_id": self.activity_type_id.id,
            "res_model_id": instance_model.id,
            "res_id": instance.id,
            "automated": True,
            "date_deadline": fields.Datetime.to_string(dt),
            "summary": self.activity_summary,
            "datapolice_id": self.id,
        }
        if self.activity_user_id:
            data["user_id"] = self.activity_user_id.id
        if self.activity_user_from_context:
            data["user_id"] = self.env.user.id

        if not self.env["mail.activity"].search_count(
            [
                ("res_id", "=", data["res_id"]),
                ("res_model_id", "=", data["res_model_id"]),
                ("datapolice_id", "=", self.id),
            ]
        ):
            self.env["mail.activity"].create(data)

    def toggle_active(self):
        self.active = not self.active

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
    def _exec_get_result(self, code, globals_dict, expect_result=True):
        code = (code or "").strip()
        code = code.splitlines()
        if code and code[-1].startswith(" ") or code[-1].startswith("\t"):
            code.append("True")
        if expect_result:
            code[-1] = "return " + code[-1]
        code = "\n".join(["  " + x for x in code])
        wrapper = "def __wrap():\n" f"{code}\n\n"
        wrapper += ("result_dict['result'] = " if expect_result else "") + "__wrap()"
        result_dict = {}
        globals_dict["result_dict"] = result_dict
        exec(wrapper, globals_dict)
        return result_dict.get("result")

    @api.model
    def _get_param_defaults(self, d):
        d.update(
            {
                "datetime": datetime,
                "date": date,
                "timedelta": timedelta,
                "env": self.env,
            }
        )
        return d

    def _fetch_objects(self):
        self.ensure_one()
        obj = self.env[self.model_id.model]
        if self.domain or not self.fetch_expr:
            domain = safe_eval(self.domain or "[]")
            order = None
            if self.date_field_id:
                order = f"{self.date_field_id.name} desc"
            instances = obj.search(domain, order=order)
        else:
            instances = self._exec_get_result(
                self.fetch_expr,
                self._get_param_defaults(
                    {
                        "model": obj,
                        "obj": obj,
                    }
                ),
            )
        if self.limit:
            instances = instances[: self.limit]
        instances = instances.with_context(prefetch_fields=False)
        return instances

    def _run_code(self, instance, expr, expect_result=True):
        exception = ""
        try:
            result = self._exec_get_result(
                expr,
                self._get_param_defaults(
                    {
                        "obj": instance,
                    }
                ),
                expect_result=expect_result,
            )
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

    def _has_queuejobs(self):
        return table_exists(self.env.cr, "queue_job")

    @api.model
    def _can_commit(self):
        if "datapolice_can_commit" in self.env.context:
            val = self.env.context.get("datapolice_can_commit")
            if val is None:
                return True
            return bool(val)
        return True

    def _make_checks(self, instances):
        RUN_ID = self.env.context.get("datapolice_identifier") or str(uuid.uuid4())
        try:
            for idx, obj in enumerate(instances, 1):
                identity_key = f"{RUN_ID}_dp_{self.id}_{obj._name}_{obj.id}"
                self._with_delay(
                    identity_key=identity_key,
                    channel=self.queuejob_channel or "root",
                    priority=self.queuejob_priority or 99,
                    enabled=not self.env.context.get("datapolice_noasync")
                    and self.queuejob_enabled,
                )._check_instance(obj, RUN_ID)
        finally:
            self._with_delay(
                enabled=not self.env.context.get("datapolice_noasync"), priority=800,
            )._start_observer(RUN_ID)
        if self._can_commit():
            self.env.cr.commit()

    def _start_observer(self, run_id):
        if self._has_queuejobs():
            count = self.env["queue.job"].search_count(
                [
                    ("identity_key", "ilike", run_id),
                    ("state", "not in", ["done", "cancel", "failed"]),
                ]
            )
            if count:
                raise RetryableJobError(
                    "Observing: found undone preceding jobs",
                    seconds=60,
                    ignore_retry=True,
                )
        self._post_status_message()

    def _check_instance(self, obj, RUN_ID):
        if not self.enabled:
            return

        def pushup(text):
            yield {
                "ok": res["ok"],
                "model": obj._name,
                "res_id": obj.id,
                "text": text,
                "date": date_value,
            }

        obj = obj.sudo()
        instance_name = str(obj.name_get()[0][1])
        check_expr = self.check_expr or "False"
        res = self._run_code(obj, check_expr)
        res["tried_to_fix"] = False
        date_value = False if not self.date_field_id else obj[self.date_field_id.name]
        success = []

        if not res["ok"] and self.fix_expr:
            res_fix = self.with_context(datapolice_run_fixdef=True)._run_code(
                obj, self.fix_expr, expect_result=False
            )
            self.env['datapolice.increment'].sudo().create({
                'dp_id': self.id,
                'run_id': RUN_ID,
                'model': obj._name,
                'res_id': obj.id,
                'ttype': 'fix',
            })
            res["tried_to_fix"] = True
            res["fix_result"] = res_fix
            res2 = self._run_code(obj, check_expr)
            res["fix_result"] = res2
            for k, v in res2.items():
                res[k] = v

            if not res["ok"] and not res["fix_result"]["ok"]:
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
                success = pushup(text)

        else:
            success = pushup(res["exception"] or "")

        errors = list(filter(lambda x: not x["ok"], success))
        self._dump_last_errors(errors)
        for error in errors:
            self._make_activity_for_error(error)

        self.env['datapolice.increment'].sudo().create({
            'ttype': 'check',
            'run_id': RUN_ID,
            'dp_id': self.id,
            'model': obj._name,
            'id': obj.id,
        })
        return errors

    def _make_activity_for_error(self, error):
        if not self.make_activity:
            return
        instance = self.env[error["model"]].sudo().browse(error["res_id"])
        self._make_activity(instance)

    def run_single_instance(self, instance):
        self.ensure_one()
        return self._check_instance(instance, RUN_ID=str(uuid.uuid4()))

    def reset_fix_counter(self):
        self.fix_counter = 0
        return True

    def run_async(self, identifier=None):
        self.with_context(
            datapolice_noasync=False, datapolice_identifier=identifier
        ).run()
        return True

    def run_now(self):
        self.with_context(datapolice_noasync=True).run()
        return True

    def run(self):
        for police in self:
            police._run_police()

    def _run_police(self):
        police = self

        police.reset()
        self.env.cr.commit()
        instances_to_check = police._fetch_objects()
        self.env.cr.commit()
        police._make_checks(instances_to_check)

    def _inc_checked(self):
        self.checked += 1

    def _inc_fixed(self):
        self.fix_counter += 1

    @api.model
    def _has_queuejobs(self):
        return hasattr(self, "with_delay")

    def _with_delay(self, *params, **kw):
        enabled = True
        if "enabled" in kw:
            enabled = kw.pop("enabled")
        if enabled and self._has_queuejobs():
            return self.with_delay(*params, **kw)
        return self

    def reset(self):
        for rec in self:
            rec.checked = 0
            for line in list(rec.lasterror_ids):
                line.sudo().unlink()

    @api.depends("errors", "checked")
    def _compute_success(self):
        for rec in self:
            if rec.checked:
                rec.ratio = 100 * (1 - rec.errors / rec.checked)
            else:
                rec.ratio = 0

    def _post_status_message(self):
        for rec in self:
            body = f"Checked: {self.checked}\nErrors: {self.errors}\nSucecss-Ratio: {rec.ratio:.2f}%"
            rec.message_post(body=body)

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

    def _get_error_text(self, errors):
        self.ensure_one()
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
                obj = self.env[error["model"]].sudo().browse(error["res_id"])
                objname = str(obj.name_get()[0][1])
                url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
                url += "#model=" + error["model"] + "&id=" + str(error["res_id"])
                link = f"<a href='{url}'>{objname}: {error['text']}</a>"
                appendix = f"<li>{link}</li>\n"
            else:
                appendix = "<li>{error}</li>\n"
            text += appendix
            if i < 50:
                small_text += appendix

        text += "</ul>"
        small_text += "</ul>"
        return small_text, text

    def _send_mail_for_single_instance(self, instance, errors):
        mail_to = self._get_all_email_recipients()
        if not mail_to:
            return
        new_small_text, new_text = self._get_error_text(errors)
        by_email = {}
        for email in mail_to.split(","):
            by_email.setdefault(email, {"text": "", "small_text": ""})
            by_email[email]["text"] = new_text
            by_email[email]["small_text"] = new_small_text
        subject = f"DataPolice: {instance.name_get()[0][1]}"
        self._send_mail_technically(by_email, subject=subject)

    def _send_mails(self, identifier):
        by_email = {}
        if self._has_queuejobs():
            if (
                self.env["queue.job"]
                .sudo()
                .search_count(
                    [
                        ("identity_key", "ilike", identifier),
                        ("state", "not in", ["done", "failed", "cancelled"]),
                    ]
                )
            ):
                raise RetryableJobError("Still running", seconds=60)

        for dp in self.filtered(lambda x: x.enabled):
            mail_to = dp._get_all_email_recipients()
            errors = [
                {
                    "text": x.exception,
                    "comment": x.comment,
                    "model": x.res_model,
                    "res_id": x.res_id,
                }
                for x in dp.lasterror_ids
            ]
            new_small_text, new_text = dp._get_error_text(errors)

            for email in mail_to.split(","):
                by_email.setdefault(email, {"text": "", "small_text": ""})
                by_email[email]["text"] += new_text
                by_email[email]["small_text"] += new_small_text
        self._send_mail_technically(by_email)

    def _send_mail_technically(self, by_email, subject=None):
        for email, texts in by_email.items():
            if not texts["text"]:
                continue
            text = base64.b64encode(texts["text"].encode("utf-8"))
            self.env["mail.mail"].sudo().create(
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
                                "name": "data_police.html",
                            },
                        ]
                    ],
                }
            ).send()

    def _dump_last_errors(self, errors):
        for rec in self:
            ids = set(x["res_id"] for x in errors)
            for error in errors:
                newline = rec.lasterror_ids.new()
                newline.res_id = error["res_id"]
                newline.res_model = self.model_id.model
                ack = self.acknowledge_ids.filtered(
                    lambda x: x.res_id == newline.res_id
                )
                exist = self.lasterror_ids.filtered(
                    lambda x: x.res_id == newline.res_id
                )
                if exist:
                    if error.get("text"):
                        exist.exception = error.get("text")
                if not ack and not exist:
                    name = (
                        self.env[newline.res_model]
                        .sudo()
                        .browse(newline.res_id)
                        .name_get()[0][1]
                    )
                    newline.name = name
                    newline.date = error.get("date", False)
                    newline.exception = error.get("text") or ""

                    rec.sudo().lasterror_ids += newline

    def show_errors(self):
        ids = self.lasterror_ids.mapped("res_id")

        return {
            "name": f"Errors of {self.name}",
            "view_type": "form",
            "res_model": self.model_id.model,
            "domain": [("id", "in", ids)],
            "views": [(False, "tree"), (False, "form")],
            "type": "ir.actions.act_window",
            "target": "current",
            "context": {
                "datapolice_id": self.id,
            },
        }

    def _is_acknowledged(self, rec):
        exist = self.acknowledge_ids.filtered(
            lambda x: x.res_model == rec._name and x.res_id == rec.id
        )
        return bool(exist)

    def acknowledge(self, rec):
        exist = self.acknowledge_ids.sudo().filtered(
            lambda x: x.res_model == rec._name and x.res_id == rec.id
        )
        lasterror = self.lasterror_ids.sudo().filtered(
            lambda x: x.res_model == rec._name and x.res_id == rec.id
        )
        name = rec.name_get()[0][1]
        data = {
            "datapolice_id": self.id,
            "name": name,
            "res_model": rec._name,
            "res_id": rec.id,
        }
        if not exist:
            data.update(
                {
                    "who_acknowledged_id": self.env.user.id,
                }
            )
            exist.create(data)
            lasterror.unlink()
        else:
            lasterror.create(data)
            exist.sudo().unlink()

    @api.depends("lasterror_ids")
    def _compute_count_errors(self):
        for rec in self:
            rec.errors = len(rec.lasterror_ids)

    @api.onchange("inform_current_user_immediately")
    def _changed_inform_current_user_immediately(self):
        for rec in self:
            if rec.inform_current_user_immediately and rec.enabled:
                trigger = rec.trigger_ids.new()
                trigger.model_id = self.model_id
                trigger.method = "write"
                trigger.link_expression = "object"
                rec.trigger_ids += trigger

    def delete_all_activities(self):
        self.env["mail.activity"].search([("datapolice_id", "=", self.id)]).unlink()

    def _compute_increment(self):
        reg = registry(self.env.cr.dbname)
        for rec in self:
            with reg.cursor() as cr:
                cr.execute("set transaction ISOLATION LEVEL READ COMMITTED;")
                sql = "select run_id from datapolice_increment where dp_id=%s and ttype=%s order by create_date desc limit 1"
                cr.execute(sql, (rec.id, 'check',))
                maxrun = cr.fetchone()
                if maxrun:
                    maxrun = maxrun[0]
                sql = "select count(*) from datapolice_increment where dp_id=%s and ttype='fix'"
                cr.execute(sql, (rec.id, ))
                rec.fix_counter = cr.fetchone()[0]

                sql = "select count(*) from datapolice_increment where dp_id=%s and run_id=%s and ttype='check'"
                cr.execute(sql, (rec.id, maxrun))
                rec.checked = cr.fetchone()[0]
                cr.execute("ROLLBACK;")
