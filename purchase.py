# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from decimal import Decimal

from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.transaction import Transaction
from trytond.i18n import gettext
from trytond.exceptions import UserError

__all__ = ['Move', 'MoveLine', 'Purchase', 'PurchaseLine',
    'HandleShipmentException']
_ZERO = Decimal('0.0')

# Add sale_stock_account_move module depends temprally, becasue this module is
#   used only by one client. If it's used by another client we will need to
#   create a little module with the stock.move property.


class Move(metaclass=PoolMeta):
    __name__ = 'account.move'

    @classmethod
    def _get_origin(cls):
        origins = super(Move, cls)._get_origin()
        if 'purchase.purchase' not in origins:
            origins.append('purchase.purchase')
        return origins


class MoveLine(metaclass=PoolMeta):
    __name__ = 'account.move.line'
    purchase_line = fields.Many2One('purchase.line', 'Purchase Line')


class Purchase(metaclass=PoolMeta):
    __name__ = 'purchase.purchase'

    @classmethod
    def process(cls, purchases):
        super(Purchase, cls).process(purchases)
        if not Transaction().context.get('stock_account_move'):
            for purchase in purchases:
                purchase.create_stock_account_move()

    def create_stock_account_move(self):
        """
        Create, post and reconcile an account_move (if it is required to do)
        with lines related to Pending Invoices accounts.
        """
        pool = Pool()
        Date = pool.get('ir.date')
        Config = pool.get('purchase.configuration')
        Move = pool.get('account.move')
        MoveLine = pool.get('account.move.line')

        if self.invoice_method != 'shipment':
            return

        events = {}
        for shipment in self.shipments:
            if shipment.state in ['received', 'done']:
                for move in shipment.incoming_moves:
                    if move.state == 'done':
                        date = move.effective_date
                        events.setdefault(date, []).append(shipment)
                        break
        for invoice in self.invoices:
            if invoice.state in ['posted', 'paid']:
                accounting_date = (
                    invoice.accounting_date or invoice.invoice_date
                    )
                events.setdefault(accounting_date, []).append(invoice)
        for shipment_return in self.shipment_returns:
            if shipment_return.state == 'done':
                events.setdefault(
                    shipment_return.effective_date,
                    [],
                    ).append(shipment_return)

        sorted_events = []
        for date in sorted(events):
            sorted_events.append([date, events[date]])

        config = Config(1)
        if not config.pending_invoice_account:
            raise UserError(gettext(
                'purchase_stock_account_move.no_pending_invoice_account'))

        with Transaction().set_context(_check_access=False):
            account_moves = []
            for date, events in sorted_events:
                account_move = self._get_stock_account_move(
                    config.pending_invoice_account, date, events)
                if account_move is not None:
                    account_moves.append(account_move)
            if account_moves:
                for account_move in account_moves:
                    account_move.save()
                Move.post(account_moves)

                to_reconcile = MoveLine.search([
                            ('move.origin', '=', str(self)),
                            ('account', '=', config.pending_invoice_account),
                            ('reconciliation', '=', None),
                            ])
                credit = sum(l.credit for l in to_reconcile)
                debit = sum(l.debit for l in to_reconcile)
                if to_reconcile and credit == debit:
                    MoveLine.reconcile(to_reconcile)

    def _get_stock_account_move(self, pending_invoice_account, date, events):
        "Return the account move for shipped quantities"
        pool = Pool()
        Move = pool.get('account.move')
        Period = pool.get('account.period')

        if self.invoice_method in ['manual', 'order']:
            return

        move_lines = []
        for line in self.lines:
            move_lines += line._get_stock_account_move_lines(
                pending_invoice_account, date, events)
        if not move_lines:
            return

        period_id = Period.find(self.company.id, date=date)
        return Move(
            origin=self,
            period=period_id,
            journal=self._get_accounting_journal(),
            date=date,
            lines=move_lines,
            )

    def _get_accounting_journal(self):
        pool = Pool()
        Journal = pool.get('account.journal')
        journals = Journal.search([
                ('type', '=', 'expense'),
                ], limit=1)
        if journals:
            journal, = journals
        else:
            journal = None
        return journal


class PurchaseLine(metaclass=PoolMeta):
    __name__ = 'purchase.line'

    analytic_required = fields.Function(fields.Boolean("Require Analytics"),
        'on_change_with_analytic_required')

    @classmethod
    def __setup__(cls):
        super(PurchaseLine, cls).__setup__()
        if hasattr(cls, 'analytic_accounts'):
            if not cls.analytic_accounts.states:
                cls.analytic_accounts.states = {}
            if cls.analytic_accounts.states.get('required'):
                cls.analytic_accounts.states['required'] |= (
                    Eval('analytic_required', False))
            else:
                cls.analytic_accounts.states['required'] = (
                    Eval('analytic_required', False))

    @fields.depends('product')
    def on_change_with_analytic_required(self, name=None):
        if not hasattr(self, 'analytic_accounts') or not self.product:
            return False

        if getattr(self.product.account_expense_used, 'analytic_required',
                    False):
            return True
        return False

    def _get_stock_account_move_lines(self, pending_invoice_account, date,
            events):
        """
        Return the account move lines for shipped quantities and
        to reconcile shipped and invoiced (and posted) quantities
        """
        pool = Pool()
        StockShipmentIn = pool.get('stock.shipment.in')
        AccountInvoice = pool.get('account.invoice')
        StockShipmentInReturn = pool.get('stock.shipment.in.return')
        Uom = pool.get('product.uom')
        MoveLine = pool.get('account.move.line')
        Currency = pool.get('currency.currency')

        if (not self.product or self.product.type == 'service' or
                not self.moves):
            # Purchase Line not shipped
            return []

        pending_quantity = 0
        unpending_quantity = 0
        for event in events:
            if isinstance(event, (StockShipmentIn,StockShipmentInReturn)):
                for move in event.moves:
                    if move.origin == self:
                        quantity = Uom.compute_qty(move.uom, move.quantity,
                            self.unit)
                        if isinstance(event, StockShipmentIn):
                            pending_quantity += quantity
                        if isinstance(event, StockShipmentInReturn):
                            unpending_quantity += quantity
            if isinstance(event, AccountInvoice):
                for line in event.lines:
                    if line.origin == self:
                        quantity = Uom.compute_qty(line.unit, line.quantity,
                            self.unit)
                        if (event.type == 'in' and
                                event.invoice_type_criteria() == '_invoice'):
                            unpending_quantity += quantity
                        elif (event.type == 'in' and
                                event.invoice_type_criteria() == '_credit_note'):
                            pending_quantity += quantity

        move_lines = MoveLine.search([
                ('purchase_line', '=', self),
                ('account', '=', pending_invoice_account),
                ('date', '=', date),
                ])
        recorded_pending_amount = sum(line.credit for line in move_lines)
        recorded_unpending_amount = sum(line.debit for line in move_lines)

        move_lines = []

        pending_amount = (Currency.compute(self.purchase.currency,
                Decimal(pending_quantity) * self.unit_price,
                self.purchase.company.currency) - recorded_pending_amount)

        if pending_amount:
            move_line = MoveLine()
            move_line.account = self.product.account_expense_used
            if move_line.account.party_required:
                move_line.party = self.purchase.party
            move_line.purchase_line = self
            if pending_amount < _ZERO:
                move_line.credit = abs(pending_amount)
                move_line.debit = _ZERO
            else:
                move_line.debit = pending_amount
                move_line.credit = _ZERO
            self._set_analytic_lines(move_line)
            move_lines.append(move_line)

            move_line = MoveLine()
            move_line.account = pending_invoice_account
            if move_line.account.party_required:
                move_line.party = self.purchase.party
            move_line.purchase_line = self
            if pending_amount > _ZERO:
                move_line.credit = pending_amount
                move_line.debit = _ZERO
            else:
                move_line.debit = abs(pending_amount)
                move_line.credit = _ZERO
            move_lines.append(move_line)

        unpending_amount = (Currency.compute(self.purchase.company.currency,
                    Decimal(unpending_quantity) * self.unit_price,
                    self.purchase.currency) - recorded_unpending_amount)

        if unpending_amount:
            move_line = MoveLine()
            move_line.account = self.product.account_expense_used
            if move_line.account.party_required:
                move_line.party = self.purchase.party
            move_line.purchase_line = self
            if unpending_amount > _ZERO:
                move_line.credit = unpending_amount
                move_line.debit = _ZERO
            else:
                move_line.debit = abs(unpending_amount)
                move_line.credit = _ZERO
            self._set_analytic_lines(move_line)
            move_lines.append(move_line)

            move_line = MoveLine()
            move_line.account = pending_invoice_account
            if move_line.account.party_required:
                move_line.party = self.purchase.party
            move_line.purchase_line = self
            if unpending_amount < _ZERO:
                move_line.credit = abs(unpending_amount)
                move_line.debit = _ZERO
            else:
                move_line.debit = unpending_amount
                move_line.credit = _ZERO
            move_lines.append(move_line)

        return move_lines

    def _set_analytic_lines(self, move_line):
        """
        Add to supplied account move line analytic lines based on purchase line
        analytic accounts value
        """
        pool = Pool()
        Date = pool.get('ir.date')

        if (not getattr(self, 'analytic_accounts', False) or
                not self.analytic_accounts):
            return []

        AnalyticLine = pool.get('analytic_account.line')
        move_line.analytic_lines = []
        for account in self.analytic_accounts:
            line = AnalyticLine()
            move_line.analytic_lines += (line,)
            line.name = self.description
            line.debit = move_line.debit
            line.credit = move_line.credit
            line.account = account.account
            line.journal = self.purchase._get_accounting_journal()
            line.date = Date.today()
            line.reference = self.purchase.reference
            line.party = self.purchase.party


class HandleShipmentException(metaclass=PoolMeta):
    __name__ = 'purchase.handle.shipment.exception'

    def transition_handle(self):
        with Transaction().set_context(stock_account_move=True):
            return super(HandleShipmentException, self).transition_handle()
