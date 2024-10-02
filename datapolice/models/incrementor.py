from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError, RedirectWarning, ValidationError
class IncChecked(models.Model):
    _name = 'datapolice.increment'

    ttype = fields.Selection([('fix', 'fix'), ('check', 'check')], index=True)
    run_id = fields.Char()
    model = fields.Char()
    res_id = fields.Integer()
    dp_id = fields.Integer(index=True)

    @api.autovacuum
    def _gc(self):
        records = self.search([('create_date', '<', fields.Datetime.subtract(fields.Datetime.now(), days=30))])
        for record in records:
            record.unlink()
            self.env.cr.commit()