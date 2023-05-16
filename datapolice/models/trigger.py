from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError, RedirectWarning, ValidationError
class Trigger(models.Model):
    _inherit = 'method_hook.trigger.mixin'
    _name = 'datapolice.trigger'

    datapolice_id = fields.Many2one("data.police", string="Datapolice")