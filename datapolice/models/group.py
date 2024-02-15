from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError, RedirectWarning, ValidationError


class Group(models.Model):
    _name = "datapolice.group"
    name = fields.Char("Name")
