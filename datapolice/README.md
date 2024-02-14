# datapolice


## Overview

* checks on triggers (any function: create, write, action_confirm)
* creates activities
* cronjobbed
* check function and fix function
* send detailed error message to user
* can raise error to end user
* when check is hit after it logs the complete trace to that problem


## Sample Code


```
<record model="data.police" id="products1">
  <field name="model">product.product</field>
  <field name="checkdef">check_incoming_noproduction_nopicking</field>
  <field name="name">Incoming stock moves, that have no production or picking-in</field>
</record>
```

```
def datapolice_check_same_lot_type(self):
    if self.origin_sales and self.matching_prod_product_ids:
        if not self.lot_type == self.matching_prod_product_ids:
            return False # can return also a string!
    elif (self.origin_buy or self.origin_buy) and self.matching_sales_product_ids:
        if not self.lot_type == self.matching_sales_product_ids:
            return False
    return True

```

or

```
<record model="data.police" id="products1">
  <field name="model">product.product</field>
  <field name="name">Incoming stock moves, that have no production or picking-in</field>
  <field name="expr">obj.name != 'not allowed'</field>
</record>
```


## Contributors

* Marc Wimmer <marc@zebroo.de>

