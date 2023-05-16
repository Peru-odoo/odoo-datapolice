from odoo import models, fields, api, _
import base64
from pathlib import Path
import tempfile
import traceback
from datetime import datetime
from odoo.exceptions import UserError, RedirectWarning, ValidationError
import logging

_logger = logging.getLogger("datapolice")

class DataPolice(models.Model):
    _name = 'data.police'

    active = fields.Boolean(default=True)
    name = fields.Char('Name', required=True, translate=True)
    fetch_expr = fields.Text("Fetch Expr", help="If given then used; return records, otherwise domain is used with model")
    check_expr = fields.Text('Expression to chec', required=False, help="Input: obj/object - return False for error, return None/True for ok, or raise Exception")
    fixdef = fields.Char('Def to fix error', required=False)
    model = fields.Char('Model', size=128, required=True)
    enabled = fields.Boolean("Enabled", default=True)
    errors = fields.Integer("Count Errors")
    domain = fields.Text('Domain')
    recipients = fields.Char("Mail-Recipients", size=1024)
    user_ids = fields.Many2many('res.users', string="Recipients (users)")
    inform_current_user_immediately  = fields.Boolean("Inform current user immediately", default=False)
    last_errors = fields.Text("Last Error Log")
    cronjob_group_id = fields.Many2one("datapolice.cronjob.group", string="Cronjob Group")
    method_triggers = fields.Many2many("method_hook.trigger", domain=[('model', '=', model)])

    def toggle_active(self):
        self.active = not self.active

    @api.constrains("src_model", "domain", "checkdef", "expr")
    def check_model_domain(self):
        for rec in self:
            if rec.domain and rec.src_model:
                raise ValidationError("Either provide src_model OR domain")
            if not rec.checkdef and not rec.expr:
                raise ValidationError("Either provide expression or check-function")

    def run_fix(self):
        self.ensure_one()
        if not self.fixdef:
            return

        self.with_context(datapolice_run_fixdef=True).run()

    @api.model
    def create(self, values):
        if 'def' in values.keys():
            raise Exception("Please use checkdef instead of def!!!")
        result = super(DataPolice, self).create(values)
        return result

    @api.constrains("recipients")
    def _check_recipients(self):
        for rec in self:
            recps = rec.recipients or ''
            recps = recps.replace(";", ",")
            def convert(x):
                x = x.strip()
                return x
            recps = list(map(convert, recps.split(",")))
            recps = ','.join(recps)
            if recps != (rec.recipients or ''):
                rec.recipients = recps


    def run(self):
        self.ensure_one()
        all_errors = {}

        def format(x):
            try:
                if not ('model' in x and 'res_id'):
                    raise Exception()
            except Exception:
                return str(x)
            else:
                return u'{}#{}: {}'.format(
                    x['model'],
                    x['res_id'],
                    x['text'],
                )

        for dp in self:
            obj = self.env[dp.model]
            errors = []
            try:
                if dp.src_model and dp.checkdef:
                    objects = getattr(self.env[dp.src_model], dp.checkdef)().with_context(prefetch_fields=False)
                else:
                    objects = obj.with_context(active_test=False, prefetch_fields=False).search(dp.domain and eval(dp.domain) or [])
            except Exception:
                if self.env.context.get('from_ui', False):
                    raise
                objects = []
                msg = traceback.format_exc()
                errors.append({
                    'res_id': 0,
                    'res_model': dp.model,
                    'text': msg,
                })

            for idx, obj in enumerate(objects, 1):
                _logger.debug(f"Checking {dp.name} {idx} of {len(objects)}")
                instance_name = "n/a"
                instance_name = self.env["data.police.formatter"].do_format(obj)

                def run_check():
                    exception = ""
                    result = False
                    self = obj  # for the expression # NOQA

                    if dp.expr:
                        try:
                            result = eval(dp.expr)
                        except Exception as e:
                            exception = str(e)
                    else:
                        try:
                            result = getattr(obj, dp.checkdef)()
                            if isinstance(result, list) and len(result) == 1:
                                if isinstance(result[0], bool):
                                    # [True] by @api.one
                                    result = result[0]
                                elif result[0] is None:
                                    result = True
                        except Exception as e:
                            exception = str(e)

                    not_ok = result is False or (result and not (result is True)) or exception
                    if not exception and isinstance(result, str):
                        exception = result

                    return {
                        'ok': not not_ok,
                        'exception': exception,
                    }

                if dp.src_model:
                    ok = {
                        'ok': False,
                        'exception': False,
                    }
                else:
                    ok = run_check()

                    if not ok['ok']:

                        if dp.fixdef:
                            fixed = False
                            try:
                                getattr(obj, dp.fixdef)()
                                fixed = True
                            except Exception:
                                msg = traceback.format_exc()
                                _logger.error(msg, exc_info=True)

                            if fixed:
                                ok = run_check()

                if not ok['ok']:
                    text = u"; ".join(x for x in [instance_name, ok.get('exception', '') or ''] if x)
                    errors += [{
                        'model': obj._name,
                        'res_id': obj.id,
                        'text': text,
                    }]
                    try:
                        _logger.error(f"Data Police {dp.name}: not ok at {obj._name} {obj.id} {text}")kj
                    except Exception:
                        pass

            dp.write({'errors': len(errors)})
            all_errors[dp] = errors
            dp.write({'last_errors': '\n'.join(format(x) for x in errors)})

        def str2mails(s):
            s = s or ''
            s = s.replace(",", ";")
            return [x.lower() for x in s.split(";") if x]

        dps = all_errors.keys()

        dp_recipients = []
        for dp in dps:
            if dp.recipients:
                dp_recipients += str2mails(dp.recipients)
            if dp.user_ids:
                dp_recipients += [x.lower() for x in dp.user_ids.mapped('email') if x]

        mail_to = ','.join(set(dp_recipients))

        text = ""
        for dp in dps:
            errors = all_errors[dp]
            if not errors:
                continue
            text += u"<h2>{}</h2>".format(dp.name)
            text += "<ul>"
            small_text = text
            for i, error in enumerate(sorted(errors, key=lambda e: (e.get('model', False), e.get('res_id', False)), reverse=True)):
                if 'model' in error and 'res_id' in error:
                    url = self.env['ir.config_parameter'].get_param('web.base.url')
                    url += "#model=" + error['model'] + "&id=" + str(error['res_id'])
                    link = u"<a href='{}'>{}</a>".format(url, error['text'])
                    appendix = u"<li>{}</li>\n".format(link)
                else:
                    appendix = u"<li>{}</li>\n".format(error)
                text += appendix
                if i < 50:
                    small_text += appendix

            text += "</ul>"
            small_text += "</ul>"

        if text:

            text = base64.encodestring(text.encode("utf-8"))
            self.env["mail.mail"].create({
                'auto_delete': True,
                'subject': 'DataPolice Run {}'.format(datetime.now().strftime("%Y-%m-%d")),
                'body_html': small_text,
                'body': small_text,
                'email_to': mail_to,
                'attachment_ids': [[0, 0, {
                    'datas': text,
                    'datas_fname': 'data_police.html',
                    'name': 'data_police.html',
                }]
                ],
            }).send()

        return True
