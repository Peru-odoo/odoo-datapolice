from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError, RedirectWarning, ValidationError
class Tags(models.Model):
    _name = 'datapolice.tag'
    name = fields.Char("Tag")