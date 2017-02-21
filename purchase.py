# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from decimal import Decimal

from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.transaction import Transaction

__all__ = ['Move', 'MoveLine', 'Purchase', 'PurchaseLine']
_ZERO = Decimal('0.0')

# Add sale_stock_account_move module depends temprally, becasue this module is
#   used only by one client. If it's used by another client we will need to
#   create a little module with the stock.move property.


class Move:
    __metaclass__ = PoolMeta
    __name__ = 'account.move'

    @classmethod
    def _get_origin(cls):
        origins = super(Move, cls)._get_origin()
        if 'purchase.purchase' not in origins:
            origins.append('purchase.purchase')
        return origins


class MoveLine:
    __metaclass__ = PoolMeta
    __name__ = 'account.move.line'
    purchase_line = fields.Many2One('purchase.line', 'Purchase Line')


class Purchase:
    __metaclass__ = PoolMeta
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

        if self.invoice_method in ['manual', 'order']:
            return

        config = Config(1)
        if not config.pending_invoice_account:
            self.raise_user_error('no_pending_invoice_account')

        with Transaction().set_context(_check_access=False):
            account_move = self._get_stock_account_move(
                config.pending_invoice_account)
            if account_move:
                account_move.save()
                Move.post([account_move])

                to_reconcile = MoveLine.search([
                            ('move.origin', '=', str(self)),
                            ('account', '=', config.pending_invoice_account),
                            ('reconciliation', '=', None),
                            ['OR',
                                # previous pending line
                                ('move', '!=', account_move),
                                # current move "to reconcile line"
                                ('purchase_line', '=', None),
                                ],
                            ])
                credit = sum(l.credit for l in to_reconcile)
                debit = sum(l.debit for l in to_reconcile)
                if to_reconcile and credit == debit:
                    MoveLine.reconcile(to_reconcile)

    def _get_stock_account_move(self, pending_invoice_account):
        "Return the account move for shipped quantities"
        pool = Pool()
        Date = pool.get('ir.date')
        Move = pool.get('account.move')
        Period = pool.get('account.period')

        if self.invoice_method in ['manual', 'order']:
            return

        move_lines = []
        for line in self.lines:
            move_lines += line._get_stock_account_move_lines(
                pending_invoice_account)
        if not move_lines:
            return

        accounting_date = Date().today()
        period_id = Period.find(self.company.id, date=accounting_date)
        return Move(
            origin=self,
            period=period_id,
            journal=self._get_accounting_journal(),
            date=accounting_date,
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


class PurchaseLine:
    __metaclass__ = PoolMeta
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
        MoveLine = pool.get('account.move.line')
        Currency = pool.get('currency.currency')

        if (not self.product or self.product.type == 'service' or
                not self.moves):
            # Purchase Line not shipped
            return []

        unposted_shiped_quantity = self._get_unposted_shipped_quantity()

        # Previously created stock account move lines (pending to invoice
        # amount)
        lines_to_reconcile = MoveLine.search([
                    ('purchase_line', '=', self),
                    ('account', '=', pending_invoice_account),
                    ('reconciliation', '=', None),
                    ])

        move_lines = []
        if not unposted_shiped_quantity and not lines_to_reconcile:
            return move_lines

        # Reconcile previously created (and not yet reconciled)
        # stock account move lines: all or partialy invoiced now
        # it use amount  because it has been created using quantities and
        # purchase line unit price => it is reliable
        amount_to_reconcile = sum(l.debit - l.credit
            for l in lines_to_reconcile) if lines_to_reconcile else _ZERO
        if amount_to_reconcile != _ZERO:
            to_reconcile_line = MoveLine()
            to_reconcile_line.account = pending_invoice_account
            if to_reconcile_line.account.party_required:
                to_reconcile_line.party = self.purchase.party
            if amount_to_reconcile > Decimal('0.0'):
                to_reconcile_line.debit = amount_to_reconcile
                to_reconcile_line.credit = _ZERO
            else:
                to_reconcile_line.credit = abs(amount_to_reconcile)
                to_reconcile_line.debit = _ZERO
            to_reconcile_line.reconciliation = None
            move_lines.append(to_reconcile_line)

        pending_amount = Currency.compute(self.purchase.company.currency,
            Decimal(unposted_shiped_quantity) * self.unit_price,
            self.purchase.currency) if unposted_shiped_quantity else _ZERO

        if amount_to_reconcile == _ZERO and not unposted_shiped_quantity:
            # no previous amount in pending invoice account nor pending to
            # invoice (and post) quantity => first time
            invoiced_amount = -pending_amount
        elif not unposted_shiped_quantity:
            # no pending to invoice and post quantity => invoiced all shiped
            invoiced_amount = amount_to_reconcile
        else:
            # invoiced partially shiped quantity
            invoiced_amount = amount_to_reconcile - pending_amount
            pending_amount = amount_to_reconcile - invoiced_amount

        if pending_amount == amount_to_reconcile:
            return []

        if invoiced_amount != _ZERO:
            invoiced_line = MoveLine()
            invoiced_line.account = self.product.account_expense_used
            if invoiced_line.account.party_required:
                invoiced_line.party = self.purchase.party
            invoiced_line.purchase = self
            if invoiced_amount > _ZERO:
                invoiced_line.credit = invoiced_amount
                invoiced_line.debit = _ZERO
            else:
                invoiced_line.debit = abs(invoiced_amount)
                invoiced_line.credit = _ZERO
            self._set_analytic_lines(invoiced_line)
            move_lines.append(invoiced_line)

        if pending_amount != _ZERO:
            pending_line = MoveLine()
            pending_line.account = pending_invoice_account
            if pending_line.account.party_required:
                pending_line.party = self.purchase.party
            pending_line.purchase_line = self
            if pending_amount > _ZERO:
                pending_line.credit = pending_amount
                pending_line.debit = _ZERO
            else:
                pending_line.debit = abs(pending_amount)
                pending_line.credit = _ZERO
            move_lines.append(pending_line)

        return move_lines

    def _get_shipped_amount(self, limit_date=None):
        pool = Pool()
        Currency = pool.get('currency.currency')

        shipped_quantity = self._get_shipped_quantity(
            limit_date)

        return Currency.compute(self.purchase.company.currency,
            Decimal(shipped_quantity) * self.unit_price,
            self.purchase.currency) if shipped_quantity else _ZERO

    def _get_shipped_quantity(self, limit_date=None):
        """
        Returns the shipped quantity which is not invoiced and posted
        """
        pool = Pool()
        Uom = pool.get('product.uom')

        sign = -1 if self.quantity < 0.0 else 1
        sended_quantity = 0.0
        for move in self.moves:
            if limit_date != None and move.effective_date and \
                    move.effective_date > limit_date:
                continue
            if move.state != 'done':
                continue

            sended_quantity += Uom.compute_qty(move.uom, move.quantity,
                self.unit)

        return sign * sended_quantity

    def _get_unposted_shipped_amount(self, limit_date=None):
        pool = Pool()
        Currency = pool.get('currency.currency')

        unposted_shipped_quantity = self._get_unposted_shipped_quantity(
            limit_date)

        return Currency.compute(self.purchase.company.currency,
            Decimal(unposted_shipped_quantity) * self.unit_price,
            self.purchase.currency) if unposted_shipped_quantity else _ZERO

    def _get_unposted_shipped_quantity(self, limit_date=None):
        """
        Returns the shipped quantity which is not invoiced and posted
        """
        pool = Pool()
        Uom = pool.get('product.uom')

        sign = -1 if self.quantity < 0.0 else 1
        posted_quantity = 0.0
        sended_quantity = 0.0
        invoice_quantity = {}
        for move in self.moves:
            if limit_date != None and move.effective_date and \
                    move.effective_date > limit_date:
                continue

            if move.state != 'done':
                continue

            sended_quantity += move.quantity

            for invoice, quantity in move.posted_quantity.iteritems():
                if invoice not in invoice_quantity:
                    invoice_quantity[invoice] = quantity
        posted_quantity = sum(invoice_quantity.values())
        return sign * Uom.compute_qty(move.uom,
            sended_quantity - posted_quantity, self.unit)

    def _set_analytic_lines(self, move_line):
        """
        Add to supplied account move line analytic lines based on purchase line
        analytic accounts value
        """
        pool = Pool()
        Date = pool.get('ir.date')

        if (not getattr(self, 'analytic_accounts', False) or
                not self.analytic_accounts.accounts):
            return []

        AnalyticLine = pool.get('analytic_account.line')
        move_line.analytic_lines = []
        for account in self.analytic_accounts.accounts:
            line = AnalyticLine()
            move_line.analytic_lines.append(line)

            line.name = self.description
            line.debit = move_line.debit
            line.credit = move_line.credit
            line.account = account
            line.journal = self.purchase._get_accounting_journal()
            line.date = Date.today()
            line.reference = self.purchase.reference
            line.party = self.purchas.party
