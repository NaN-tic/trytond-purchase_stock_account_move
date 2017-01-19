#The COPYRIGHT file at the top level of this repository contains the full
#copyright notices and license terms.
from trytond.pool import Pool
import configuration
import purchase


def register():
    Pool.register(
        configuration.Configuration,
        configuration.ConfigurationCompany,
        purchase.Move,
        purchase.MoveLine,
        purchase.Purchase,
        purchase.PurchaseLine,
        module='purchase_stock_account_move', type_='model')
