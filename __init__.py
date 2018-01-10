#The COPYRIGHT file at the top level of this repository contains the full
#copyright notices and license terms.
from trytond.pool import Pool
from . import configuration
from . import purchase
from . import shipment

def register():
    Pool.register(
        configuration.Configuration,
        configuration.ConfigurationCompany,
        purchase.Move,
        purchase.MoveLine,
        purchase.Purchase,
        purchase.PurchaseLine,
        shipment.ShipmentIn,
        module='purchase_stock_account_move', type_='model')
    Pool.register(
        purchase.HandleShipmentException,
        module='purchase_stock_account_move', type_='wizard')
