import odoo
from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError, RedirectWarning, ValidationError


class Logging(models.Model):
    _name = "datapolice.log"
    _ordre = 'create_date desc'

    datapolice_id = fields.Many2one("data.police")
    excinfo = fields.Char("Exception")
    stacktrace = fields.Text("Stack Trace")

    @api.model
    def _insert_log(self, text, trace, datapolice_id):

        with odoo.api.Environment.manage():
            with odoo.registry(self.env.cr.dbname).cursor() as new_cr:
                new_cr.execute(
                    (
                        "insert into datapolice_log(create_date, excinfo, stacktrace, datapolice_id) "
                        "values(%s, %s, %s, %s)"
                    ),
                    (fields.Datetime.now(), text, trace, datapolice_id),
                )
                new_cr.commit()