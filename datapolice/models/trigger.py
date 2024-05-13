import odoo
import traceback
from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError, RedirectWarning, ValidationError


class BaseTrigger(models.AbstractModel):
    _name = "datapolice.trigger.abstract"

    datapolice_id = fields.Many2one(
        "data.police", string="Datapolice", ondelete="cascade"
    )

    def _trigger(self, instance, args_packed, method_name):
        errors = self.datapolice_id.run_single_instance(instance)
        trace = "".join(traceback.format_stack())
        datapolice_id = self.datapolice_id.id

        if errors:
            text = (
                f"Error at {instance.name_get()[0][1]}\n"
                f"for: {self.datapolice_id.name}\n"
                f"Errors: {errors}"
            )
            self.env["datapolice.log"].sudo()._insert_log(text, trace, datapolice_id)

            if self.datapolice_id.inform_current_user_immediately:
                raise ValidationError(text)
        else:
            self.env["datapolice.log"].sudo()._insert_log("", trace, datapolice_id)

        self.datapolice_id._send_mail_for_single_instance(instance, errors)


class Trigger(models.Model):
    _inherit = ["datapolice.trigger.abstract", "method_hook.trigger.mixin"]
    _name = "datapolice.trigger"


class FieldTrigger(models.Model):
    _inherit = ["datapolice.trigger.abstract", "method_hook.field_trigger"]
    _name = "datapolice.trigger_field"
