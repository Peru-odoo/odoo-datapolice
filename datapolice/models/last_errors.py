from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError, RedirectWarning, ValidationError


class DBLastError(models.Model):
    _inherit = "datapolice.ack"
    _name = "datapolice.lasterror"

    def acknowledge(self):
        for rec in self:
            obj = self.env[rec.datapolice_id.model_id.model].browse(rec.res_id)
            rec.datapolice_id.acknowledge(obj)
