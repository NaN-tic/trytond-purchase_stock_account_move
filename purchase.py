# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from decimal import Decimal

from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.transaction import Transaction

__all__ = ['Purchase', 'PurchaseLine', 'InvoiceLine', 'Move']
__metaclass__ = PoolMeta


class Purchase:
    __name__ = 'purchase.purchase'

    @classmethod
    def __setup__(cls):
        super(Purchase, cls).__setup__()
        cls._error_messages.update({
                'no_pending_invoice_account': ('There is no Pending Invoice '
                    'Account Defined. Please define one in purchase '
                    'configuration.'),
                })

    @classmethod
    def process(cls, purchases):
        super(Purchase, cls).process(purchases)
        for purchase in purchases:
            if purchase.invoice_method not in ['manual', 'order']:
                if Transaction().user:
                    with Transaction().set_user(0, set_context=True):
                        purchase.create_account_move()
                        purchase.reconcile_moves()
                else:
                    purchase.create_account_move()
                    purchase.reconcile_moves()

    def create_account_move(self):
        "Creates account move for not invoiced shipments"
        pool = Pool()
        Move = pool.get('account.move')
        Config = pool.get('purchase.configuration')
        config = Config(1)
        if not config.pending_invoice_account:
            self.raise_user_error('no_pending_invoice_account')

        shipment_amount = sum(self._get_shipment_amount().values())
        accounting_amount = self._get_accounting_amount()
        amount = shipment_amount - accounting_amount
        if amount != Decimal('0.0'):
            move = self._get_account_move()
            move.save()
            Move.post([move])

    def reconcile_moves(self):
        " Reconciles account moves if purchase is finished "
        pool = Pool()
        Line = pool.get('account.move.line')
        Config = pool.get('purchase.configuration')

        skip_ids = set(x.id for x in self.invoices_ignored)
        skip_ids.update(x.id for x in self.invoices_recreated)
        invoices = [i for i in self.invoices if i.id not in skip_ids]
        if any(i.state not in ('posted', 'paid') for i in invoices) or \
                self.shipment_state != 'received':
            return
        config = Config(1)
        lines = []
        lines.extend(Line.search([
                    ('move', 'in', [inv.move.id for inv in invoices]),
                    ('account', '=', config.pending_invoice_account),
                    ('reconciliation', '=', None),
                    ]))
        lines.extend(Line.search([
                    ('move.origin', '=', str(self)),
                    ('account', '=', config.pending_invoice_account),
                    ('reconciliation', '=', None),
                    ]))
        if lines:
            Line.reconcile(lines)

    def _get_shipment_amount(self):
        " Returns the shipped amount grouped by account"
        pool = Pool()
        Uom = pool.get('product.uom')
        Currency = pool.get('currency.currency')
        ret = {}
        for line in self.lines:
            if not line.product or line.product.type == 'service':
                continue
            skip_ids = set(x.id for x in line.moves_ignored)
            skip_ids.update(x.id for x in line.moves_recreated)
            sign = -1 if line.quantity < 0.0 else 1
            for move in line.moves:
                if move.state != 'done' \
                        and move.id not in skip_ids:
                    continue
                quantity = Uom.compute_qty(move.uom, move.quantity, line.unit)
                amount = Currency.compute(self.company.currency,
                    Decimal(quantity) * line.unit_price * sign, self.currency)
                account = move.product.account_expense_used.id
                if account in ret:
                    ret[account] += amount
                else:
                    ret[account] = amount
        return ret

    def _get_accounting_amount(self):
        " Returns the amount in accounting for this purchase"
        pool = Pool()
        Line = pool.get('account.move.line')
        Config = pool.get('purchase.configuration')

        config = Config(1)

        lines = Line.search([
                ('move.origin', '=', str(self)),
                ('account', '=', config.pending_invoice_account),
                ])
        if not lines:
            return Decimal('0.0')
        return sum(l.credit - l.debit for l in lines)

    def _get_account_move(self):
        " Return the move object to create "
        pool = Pool()
        Move = pool.get('account.move')
        Date = pool.get('ir.date')
        Period = pool.get('account.period')
        Journal = pool.get('account.journal')

        accounting_date = Date().today()
        period_id = Period.find(self.company.id, date=accounting_date)

        journals = Journal.search([
                ('type', '=', 'expense'),
                ], limit=1)
        if journals:
            journal, = journals
        else:
            journal = None

        return Move(
            origin=self,
            period=period_id,
            journal=journal,
            date=accounting_date,
            lines=self._get_account_move_lines(),
            )

    def _get_account_move_lines(self):
        " Return the move object to create "
        pool = Pool()
        Account = pool.get('account.account')
        Line = pool.get('account.move.line')
        Config = pool.get('purchase.configuration')
        config = Config(1)

        shipment_amount_values = self._get_shipment_amount()
        shipment_amount = sum(shipment_amount_values.values())
        accounting_amount = self._get_accounting_amount()

        lines = []
        #Line with invoice_pending amount
        line = Line()
        line.account = config.pending_invoice_account
        line.party = self.party
        amount = shipment_amount - accounting_amount
        if amount > 0:
            line.credit = abs(amount)
        else:
            line.debit = abs(amount)
        lines.append(line)

        divisor = amount / shipment_amount
        #One line for each product expense account
        for account, account_amount in shipment_amount_values.iteritems():
            line = Line()
            line.account = Account(account)
            line.party = self.party
            amount = self.currency.round(account_amount * divisor)
            if amount > 0:
                line.debit = abs(amount)
            else:
                line.credit = abs(amount)
            lines.append(line)

        return lines


class PurchaseLine:
    __name__ = 'purchase.line'

    def get_invoice_line(self, invoice_type):
        pool = Pool()
        Config = pool.get('purchase.configuration')
        config = Config(1)
        lines = super(PurchaseLine, self).get_invoice_line(invoice_type)
        if not self.product or self.product.type == 'service':
            return lines
        for line in lines:
            line.pending_invoice_account = config.pending_invoice_account.id
            line.account = config.pending_invoice_account.id
        return lines


class InvoiceLine:
    __name__ = 'account.invoice.line'

    pending_in_invoice_account = fields.Function(fields.Many2One(
            'account.account', 'Pending Invoice Account', required=True,
            domain=[
                ('kind', '=', 'receivable'),
                ]), 'get_pending_in_invoice_account')

    @classmethod
    def __setup__(cls):
        super(InvoiceLine, cls).__setup__()
        if not 'pending_in_invoice_account' in cls.account.depends:
            receivable = ('id', '=', Eval('pending_in_invoice_account', -1))
            cls.account.domain = ['OR', cls.account.domain, receivable]
            cls.account.depends.append('pending_in_invoice_account')

    @classmethod
    def get_pending_in_invoice_account(cls, invoices, names):
        pool = Pool()
        Config = pool.get('purchase.configuration')
        config = Config(1)

        default_account = (config.pending_invoice_account.id
            if config.pending_invoice_account else None)

        account = dict((i.id, default_account) for i in invoices)
        result = {}
        for name in names:
            result[name] = account
        return result


class Move:
    __name__ = 'account.move'

    @classmethod
    def _get_origin(cls):
        origins = super(Move, cls)._get_origin()
        if not 'purchase.purchase' in origins:
            origins.append('purchase.purchase')
        return origins
