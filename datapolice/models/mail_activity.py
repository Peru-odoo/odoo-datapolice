from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError, RedirectWarning, ValidationError
class MailActivity(models.Model):
    _inherit = 'mail.activity'

    datapolice_id = fields.Many2one('data.police', string="Datapolice")
