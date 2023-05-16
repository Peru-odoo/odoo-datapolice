from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError, RedirectWarning, ValidationError
class Trigger(models.Model):
    _inherit = 'method_hook.trigger.mixin'
    _name = 'datapolice.trigger'

    datapolice_id = fields.Many2one("data.police", string="Datapolice")

    def _trigger(self, instance):
        errors = self.datapolice_id.run_single_instance(instance)
        errors = ';'.join(errors)

        if instance.inform_current_user_immediately:
            text = (
                f"Error at {instance.name_get()[0][1]}\n"
                f"for: {self.datapolice_id.name}\n"
                f"Errors: {errors}"
            )
            raise ValidationError(text)