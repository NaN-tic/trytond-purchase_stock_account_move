# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from decimal import Decimal

from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction

__all__ = ['Purchase', 'Move', 'Line']
__metaclass__ = PoolMeta
_ZERO = Decimal('0.0')


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
                with Transaction().set_context(_check_access=False):
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

        if (self._get_shipment_amount() - self._get_accounting_amount() !=
                _ZERO):
            move = self._get_account_move()
            if move:
                move.save()
                Move.post([move])

    def reconcile_moves(self):
        " Reconciles account moves if purchase is finished "
        pool = Pool()
        Move = pool.get('account.move')
        Line = pool.get('account.move.line')
        Config = pool.get('purchase.configuration')

        config = Config(1)
        invoiced = self._get_invoiced_amount()
        invoiced_amount = sum(invoiced.values(), _ZERO)

        to_reconcile = Line.search([
                    ('move.origin', '=', str(self)),
                    ('account', '=', config.pending_invoice_account),
                    ('reconciliation', '=', None),
                    ])
        if invoiced_amount == _ZERO or not to_reconcile:
            return

        move = self._get_reconcile_move()
        move_lines = []
        total_invoiced_amount = _ZERO
        #One line for each sale line
        for purchase_line, invoice_amount in invoiced.iteritems():
            line = Line()
            line.account = purchase_line.product.account_expense_used
            if line.account.party_required:
                line.party = self.party
            if invoice_amount > _ZERO:
                line.credit = invoice_amount
                line.debit = _ZERO
            else:
                line.debit = abs(invoice_amount)
                line.credit = _ZERO
            line.purchase_line = purchase_line
            self._set_analytic_lines(line, purchase_line)
            move_lines.append(line)
            total_invoiced_amount += invoice_amount

        amount = sum(l.credit - l.debit for l in to_reconcile)
        line = Line()
        line.account = config.pending_invoice_account
        if line.account.party_required:
            line.party = self.party
        if amount > Decimal('0.0'):
            line.debit = amount
        else:
            line.credit = abs(amount)
        line.reconciliation = None
        move.lines = [line]
        move.save()
        #Reload in order to get the id and make reconcile work.
        line, = move.lines
        to_reconcile.append(line)

        pending_amount = amount - total_invoiced_amount
        line = Line()
        line.account = config.pending_invoice_account
        if line.account.party_required:
            line.party = self.party
        if pending_amount > Decimal('0.0'):
            line.credit = pending_amount
        else:
            line.debit = abs(pending_amount)
        move_lines.append(line)
        move.lines += tuple(move_lines)

        move.save()
        Move.post([move])
        Line.reconcile(to_reconcile)

    def _get_shipment_quantity(self):
        " Returns the shipped quantity grouped by sale_line"
        pool = Pool()
        Uom = pool.get('product.uom')
        ret = {}
        for line in self.lines:
            if not line.product or line.product.type == 'service':
                continue
            sign = -1 if line.quantity < 0.0 else 1
            for move in line.moves:
                if move.state != 'done':
                    continue
                quantity = Uom.compute_qty(move.uom, move.quantity, line.unit)
                quantity *= sign
                if line in ret:
                    ret[line] += quantity
                else:
                    ret[line] = quantity
        return ret

    def _get_shipment_amount(self):
        "Return the total shipped amount"
        pool = Pool()
        Currency = pool.get('currency.currency')
        amount = _ZERO
        for line, quantity in self._get_shipment_quantity().iteritems():
            amount += Currency.compute(self.company.currency,
                Decimal(quantity) * line.unit_price, self.currency)
        return amount

    def _get_accounting_amount(self):
        "Returns the amount in accounting for this purchase"
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

    def _get_invoiced_amount(self):
        " Returns the invoiced amount grouped by account"
        skip_ids = set(x.id for x in self.invoices_ignored)
        skip_ids.update(x.id for x in self.invoices_recreated)
        moves = [i.move for i in self.invoices if i.id not in skip_ids
            and i.move]

        ret = {}
        for purchase_line in self.lines:
            for invoice_line in purchase_line.invoice_lines:
                if (invoice_line.invoice and invoice_line.invoice.move and
                        invoice_line.invoice.move in moves):
                    amount = invoice_line.amount
                    if 'credit_note' in invoice_line.invoice_type:
                        amount = amount.copy_negate()
                    if purchase_line in ret:
                        ret[purchase_line] += amount
                    else:
                        ret[purchase_line] = amount
        return ret

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

    def _get_account_move(self):
        "Return the move object to create"
        pool = Pool()
        Move = pool.get('account.move')
        Date = pool.get('ir.date')
        Period = pool.get('account.period')

        accounting_date = Date().today()
        period_id = Period.find(self.company.id, date=accounting_date)

        lines = self._get_account_move_lines()
        if all(getattr(l, 'credit', _ZERO) == _ZERO and
                getattr(l, 'debit', _ZERO) == _ZERO for l in lines):
            return

        return Move(
            origin=self,
            period=period_id,
            journal=self._get_accounting_journal(),
            date=accounting_date,
            lines=lines,
            )

    def _get_reconcile_move(self):
        "Return the move object to create"
        pool = Pool()
        Move = pool.get('account.move')
        Date = pool.get('ir.date')
        Period = pool.get('account.period')

        accounting_date = Date().today()
        period_id = Period.find(self.company.id, date=accounting_date)

        return Move(
            origin=self,
            period=period_id,
            journal=self._get_accounting_journal(),
            date=accounting_date,
            )

    def _get_account_move_lines(self):
        "Return the move object to create"
        pool = Pool()
        Line = pool.get('account.move.line')
        Currency = pool.get('currency.currency')
        Config = pool.get('purchase.configuration')
        config = Config(1)

        shipment_amount = _ZERO

        posted_amounts = {}.fromkeys([x for x in self.lines], _ZERO)
        for line in Line.search([
                    ('purchase_line', 'in', [x.id for x in self.lines])
                    ]):
            posted_amounts[line.purchase_line] += line.debit - line.credit

        lines = []
        #One line for each product_line
        for purchase_line, quantity in \
                self._get_shipment_quantity().iteritems():
            account = purchase_line.product.account_expense_used
            line = Line()
            line.account = account
            if account.party_required:
                line.party = self.party
            amount = Currency.compute(self.company.currency,
                Decimal(quantity) * purchase_line.unit_price, self.currency)
            amount -= posted_amounts[purchase_line]
            if amount > 0:
                line.debit = abs(amount)
                line.credit = _ZERO
            else:
                line.credit = abs(amount)
                line.debit = _ZERO
            line.purchase_line = purchase_line
            self._set_analytic_lines(line, purchase_line)
            lines.append(line)
            shipment_amount += amount

        #Line with invoice_pending amount
        line = Line()
        line.account = config.pending_invoice_account
        if line.account.party_required:
            line.party = self.party
        if shipment_amount > 0:
            line.credit = abs(shipment_amount)
        else:
            line.debit = abs(shipment_amount)
        lines.append(line)

        return lines

    def _set_analytic_lines(self, move_line, purchase_line):
        "Sets the analytic_lines for a move_line related to purchase_line"
        pool = Pool()
        Date = pool.get('ir.date')
        try:
            AnalyticLine = pool.get('analytic_account.line')
        except KeyError:
            return []

        lines = []
        for entry in purchase_line.analytic_accounts:
            if not entry.account:
                continue
            line = AnalyticLine()
            line.name = purchase_line.description
            line.debit = move_line.debit
            line.credit = move_line.credit
            line.account = entry.account
            line.journal = self._get_accounting_journal()
            line.date = Date.today()
            line.reference = self.reference
            if hasattr(move_line, 'party'):
                line.party = move_line.party
            lines.append(line)
        move_line.analytic_lines = lines
        return lines


class Move:
    __name__ = 'account.move'

    @classmethod
    def _get_origin(cls):
        origins = super(Move, cls)._get_origin()
        if not 'purchase.purchase' in origins:
            origins.append('purchase.purchase')
        return origins


class Line:
    __name__ = 'account.move.line'
    purchase_line = fields.Many2One('purchase.line', 'Purchase Line')
