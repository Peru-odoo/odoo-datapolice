from odoo import models, api, _

class Product(models.Model):
    _inherit = 'product.product'

    def check_recursion_in_bom(self):
        self.ensure_one()
        if not hasattr(self, 'get_descendants'):
            return True
        try:
            self.get_descendants(throw_error=True)
        except Exception:
            return False
        return True

class Bom(models.Model):
    _inherit = 'mrp.bom'

    def check_inactive_products_in_boms(self):
        self.ensure_one()
        if not self.product_id.active:
            return True

        if any(not active for active in self.with_context(active_test=False).mapped('bom_line_ids.product_id.active')):
            return "Bom of {} {}".format(self.product_id.default_code, self.product_id.name)
