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
        Config = pool.get('purchase.configuration')
        Move = pool.get('account.move')
        MoveLine = pool.get('account.move.line')
        config = Config(1)
        if self.invoice_method != 'shipment':
            return

        with Transaction().set_context(_check_access=False):
            account_moves = []
            account_moves = self._get_stock_account_move(
                    config.pending_invoice_account)

            if account_moves:
                Move.save(account_moves)
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

    def _get_stock_account_move(self, pending_invoice_account):
        "Return the account move for shipped quantities"

        if self.invoice_method in ['manual', 'order']:
            return
        account_moves = []
        for line in self.lines:
            line_moves = line._get_stock_account_move_lines(
                pending_invoice_account)
            account_moves.extend(line_moves)
        return account_moves

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

    def _get_stock_account_move_lines(self, pending_invoice_account):
        """
        Return the account move lines for shipped quantities and
        to reconcile shipped and invoiced (and posted) quantities
        """
        pool = Pool()
        Uom = pool.get('product.uom')
        AccountMoveLine = pool.get('account.move.line')
        AccountMove = pool.get('account.move')
        Currency = pool.get('currency.currency')
        Period = pool.get('account.period')
        Date = pool.get('ir.date')

        if (not self.product or self.product.type == 'service' or
                not self.moves):
            # Purchase Line not shipped
            return []
        quantities = {}
        for invoice_line in self.invoice_lines:
            if invoice_line in self.purchase.invoice_lines_ignored:
                continue
            if invoice_line.stock_moves:
                accounting_date = invoice_line.stock_moves[0].effective_date
            elif invoice_line.invoice:
                accounting_date = invoice_line.invoice.invoice_date
            else:
                accounting_date = self.delivery_date
            quantity = Uom.compute_qty(
                    invoice_line.unit, invoice_line.quantity, self.unit)
            if accounting_date not in quantities:
                quantities[accounting_date] = 0.0
            quantities[accounting_date] += quantity
            if ((invoice_line.invoice
                    and invoice_line.invoice.state in ['posted', 'paid'])):
                accounting_date = (
                    invoice_line.invoice.accounting_date
                    or invoice_line.invoice.invoice_date
                    or invoice_line.invoice.write_date.date()
                    )
                quantity = Uom.compute_qty(
                        invoice_line.unit, invoice_line.quantity, self.unit)
                if accounting_date not in quantities:
                    quantities[accounting_date] = 0.0
                quantities[accounting_date] -= quantity

        amounts = {}
        move_lines = AccountMoveLine.search([
            ('purchase_line', '=', self),
            ('account', '=', pending_invoice_account),
            ])
        for move_line in move_lines:
            if move_line.date not in amounts:
                amounts[move_line.date] = Decimal(0)
            amounts[move_line.date] += (move_line.credit - move_line.debit)

        moves = []
        for date in sorted(list(set(quantities.keys()) | set(amounts.keys()))):
            move_lines = []
            pending_quantity = quantities.get(date, 0.0)
            recorded_pending_amount = amounts.get(date, Decimal(0))

            with Transaction().set_context(date=date):
                pending_amount = (Currency.compute(self.purchase.currency,
                        Decimal(pending_quantity) * self.unit_price,
                        self.purchase.company.currency) - recorded_pending_amount)

            if pending_amount:
                move_line = AccountMoveLine()
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

                move_line = AccountMoveLine()
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
            if move_lines:
                period_id = Period.find(self.company.id, date=date,
                    exception=False)
                flag = False
                if not period_id:
                    period_id = Period.find(self.company.id, date=Date.today())
                    move_date = Date.today()
                    flag = True
                else:
                    move_date = date
                move = AccountMove(
                    origin=self.purchase,
                    period=period_id,
                    journal=self.purchase._get_accounting_journal(),
                    date=move_date,
                    lines=move_lines,)
                if flag:
                    move.description = 'X ' + str(date)
                moves.append(move)
        return moves

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
