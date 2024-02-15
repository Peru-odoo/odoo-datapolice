from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError, RedirectWarning, ValidationError


class Base(models.AbstractModel):
    _inherit = "base"

    def dp_acknowledge(self):
        for rec in self:
            dp_id = self.env.context.get("datapolice_id")

            dp = self.env['data.police'].sudo().browse(dp_id)
            dp.acknowledge(rec)
