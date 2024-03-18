from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError, RedirectWarning, ValidationError


class DBAcknowledged(models.Model):
    _name = "datapolice.ack"

    datapolice_id = fields.Many2one("data.police", required=True, ondelete="cascade")

    res_model = fields.Char("model", required=True)
    res_id = fields.Integer("ID", required=True)
    name = fields.Char("Name", required=True)
    comment = fields.Text("Comment")
    who_acknowledged_id = fields.Many2one('res.users')
    exception = fields.Text("Exception")

    def unacknowledge(self):
        for rec in self:
            obj = self.env[rec.datapolice_id.model_id.model].browse(rec.res_id)
            rec.datapolice_id.acknowledge(obj)

    def open(self):
        self.ensure_one()
        return {
            "view_type": "form",
            "res_model": self._name,
            "res_id": self.id,
            "views": [(False, "form")],
            "type": "ir.actions.act_window",
            "target": "current",
        }
