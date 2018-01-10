# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import PoolMeta
from trytond.transaction import Transaction

__all__ = ['ShipmentIn']


class ShipmentIn:
    __metaclass__ = PoolMeta
    __name__ = 'stock.shipment.in'

    @classmethod
    def cancel(cls, shipments):
        with Transaction().set_context(stock_account_move=True):
            super(ShipmentIn, cls).cancel(shipments)
