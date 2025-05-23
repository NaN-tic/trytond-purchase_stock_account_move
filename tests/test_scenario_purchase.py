import datetime
import unittest
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from proteus import Model, Wizard
from trytond.modules.account.tests.tools import (create_chart,
                                                 create_fiscalyear, create_tax,
                                                 get_accounts)
from trytond.modules.account_invoice.tests.tools import (
    create_payment_term, set_fiscalyear_invoice_sequences)
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.modules.stock.exceptions import MoveFutureWarning
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules, set_user


class Test(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):

        # """

        # Create a purchase, with method invoice on shipment, and process it.

        # Create it's shipment and post it. After post will create automatically for each

        # move an account move with lines related to Pending Invoices accounts.

        # Post the invoice related to that purchase. That post create an acount move to

        # reconcile the Pending Invoice account move created before with the stock moves

        # post. If the quantity are not the same reconcile the existent move

        # and create new account move line, in the same account move, with the rest of

        # amount. Leaving the not invoice quantites pending to reconcile.

        # If you received the purchase quantities in 2 different shipments, the amount of

        # Pending Invoices accounts will be acumulated in the same account move.

        # The same process with negative purchase.

        # On refund that invoice don't do anyting. (not implemented on test)

        # """

        # Imports
        today = datetime.date.today()
        next_year = datetime.date.today() + relativedelta(years=1)

        # Activate purchase_stock_account_move
        config = activate_modules('purchase_stock_account_move')

        # Create company
        _ = create_company()
        company = get_company()

        # Reload the context
        User = Model.get('res.user')
        Group = Model.get('res.group')
        config._context = User.get_preferences(True, config.context)

        # Create purchase user
        purchase_user = User()
        purchase_user.name = 'Purchase'
        purchase_user.login = 'purchase'
        purchase_group, = Group.find([('name', '=', 'Purchase')])
        purchase_user.groups.append(purchase_group)
        purchase_user.save()

        # Create stock user
        stock_user = User()
        stock_user.name = 'Stock'
        stock_user.login = 'stock'
        stock_group, = Group.find([('name', '=', 'Stock')])
        stock_user.groups.append(stock_group)
        stock_user.save()

        # Create account user
        account_user = User()
        account_user.name = 'Account'
        account_user.login = 'account'
        account_group, = Group.find([('name', '=', 'Accounting')])
        account_user.groups.append(account_group)
        account_user.save()

        # Create fiscal year
        fiscalyear = set_fiscalyear_invoice_sequences(
            create_fiscalyear(company))
        fiscalyear.click('create_period')
        fiscalyear2 = set_fiscalyear_invoice_sequences(
            create_fiscalyear(company, today=next_year))
        fiscalyear2.click('create_period')

        # Create chart of accounts
        _ = create_chart(company)
        accounts = get_accounts(company)
        revenue = accounts['revenue']
        expense = accounts['expense']
        payable = accounts['payable']

        # Create pending account and another expense account
        Account = Model.get('account.account')
        pending_payable = Account()
        pending_payable.code = 'PR'
        pending_payable.name = 'Pending payable'
        pending_payable.type = payable.type
        pending_payable.reconcile = True
        pending_payable.save()

        # Configure purchase to track pending_payables in accounting
        PurchaseConfig = Model.get('purchase.configuration')
        purchase_config = PurchaseConfig(1)
        purchase_config.purchase_invoice_method = 'shipment'
        purchase_config.pending_invoice_account = pending_payable
        purchase_config.save()

        # Create parties
        Party = Model.get('party.party')
        supplier = Party(name='Supplier')
        supplier.save()
        customer = Party(name='Customer')
        customer.save()

        # Create tax
        tax = create_tax(Decimal('.10'))
        tax.save()

        # Create account categories
        ProductCategory = Model.get('product.category')
        account_category = ProductCategory(name="Account Category")
        account_category.accounting = True
        account_category.account_expense = expense
        account_category.account_revenue = revenue
        account_category.save()
        account_category_tax, = account_category.duplicate()
        account_category_tax.supplier_taxes.append(tax)
        account_category_tax.save()

        # Create products
        ProductUom = Model.get('product.uom')
        unit, = ProductUom.find([('name', '=', 'Unit')])
        ProductTemplate = Model.get('product.template')
        Product = Model.get('product.product')
        product1 = Product()
        template1 = ProductTemplate()
        template1.name = 'product'
        template1.account_category = account_category_tax
        template1.default_uom = unit
        template1.type = 'goods'
        template1.purchasable = True
        template1.list_price = Decimal('20')
        template1.cost_price_method = 'fixed'
        template1.save()
        product1, = template1.products
        product1.cost_price = Decimal('10')
        product1.save()
        template2 = ProductTemplate()
        template2.name = 'product'
        template2.account_category = account_category_tax
        template2.default_uom = unit
        template2.type = 'goods'
        template2.purchasable = True
        template2.list_price = Decimal('40')
        template2.cost_price_method = 'fixed'
        template2.save()
        product2, = template2.products
        product2.template = template2
        product2.cost_price = Decimal('20')
        product2.save()

        # Create payment term
        payment_term = create_payment_term()
        payment_term.save()

        # Create an Inventory
        set_user(stock_user)
        Inventory = Model.get('stock.inventory')
        InventoryLine = Model.get('stock.inventory.line')
        Location = Model.get('stock.location')
        storage, = Location.find([
            ('code', '=', 'STO'),
        ])
        inventory = Inventory()
        inventory.location = storage
        inventory.save()
        inventory_line = InventoryLine(product=product1, inventory=inventory)
        inventory_line.quantity = 100.0
        inventory_line.expected_quantity = 0.0
        inventory.save()
        inventory_line.save()
        inventory_line = InventoryLine(product=product2, inventory=inventory)
        inventory_line.quantity = 100.0
        inventory_line.expected_quantity = 0.0
        inventory.save()
        inventory_line.save()
        Inventory.confirm([inventory.id], config.context)
        self.assertEqual(inventory.state, 'done')

        # Purchase products
        set_user(purchase_user)
        Purchase = Model.get('purchase.purchase')
        purchase = Purchase()
        purchase.party = supplier
        purchase.payment_term = payment_term
        purchase_line = purchase.lines.new()
        purchase_line.product = product1
        purchase_line.quantity = 5.0
        purchase_line.unit_price = product1.cost_price
        purchase_line = purchase.lines.new()
        purchase_line.type = 'comment'
        purchase_line.description = 'Comment'
        purchase_line = purchase.lines.new()
        purchase_line.product = product2
        purchase_line.quantity = 5.0
        purchase_line.unit_price = product2.cost_price
        purchase.click('quote')
        purchase.click('confirm')
        self.assertEqual(purchase.state, 'processing')
        purchase.reload()
        self.assertEqual(len(purchase.moves), 2)

        self.assertEqual(len(purchase.shipment_returns), 0)

        self.assertEqual(len(purchase.invoices), 0)
        set_user(account_user)
        AccountMoveLine = Model.get('account.move.line')
        moves = AccountMoveLine.find([('origin', '=',
                                       'purchase.purchase,' + str(purchase.id)),
                                      ('account', '=', pending_payable.id)])
        self.assertEqual(len(moves), 0)

        # Not yet linked to invoice lines
        set_user(purchase_user)
        stock_move1, stock_move2 = sorted(purchase.moves,
                                          key=lambda m: m.quantity)
        self.assertEqual(len(stock_move1.invoice_lines), 0)
        self.assertEqual(len(stock_move2.invoice_lines), 0)

        # Validate Shipments
        moves = purchase.moves
        set_user(stock_user)
        Move = Model.get('stock.move')
        ShipmentIn = Model.get('stock.shipment.in')
        shipment = ShipmentIn()
        shipment.supplier = supplier
        for move in moves:

            incoming_move = Move(id=move.id)

            incoming_move.quantity = 1

            shipment.incoming_moves.append(incoming_move)
        shipment.save()
        shipment.click('receive')
        shipment.click('do')
        set_user(account_user)
        account_moves = AccountMoveLine.find([
            ('move_origin', '=', 'purchase.purchase,' + str(purchase.id)),
            ('account', '=', pending_payable.id),
        ])
        self.assertEqual(len(account_moves), 2)
        self.assertEqual(sum([a.credit for a in account_moves]),
                         Decimal('30.00'))
        set_user(purchase_user)
        purchase.reload()
        moves = purchase.moves.find([('state', '=', 'draft')])
        set_user(stock_user)
        shipment = ShipmentIn()
        shipment.supplier = supplier
        for move in moves:

            incoming_move = Move(id=move.id)

            shipment.incoming_moves.append(incoming_move)
        shipment.save()
        ShipmentIn.receive([shipment.id], config.context)
        ShipmentIn.do([shipment.id], config.context)
        set_user(account_user)
        account_moves = AccountMoveLine.find([
            ('move_origin', '=', 'purchase.purchase,' + str(purchase.id)),
            ('account', '=', pending_payable.id),
        ])
        self.assertEqual(len(account_moves), 4)
        self.assertEqual(sum([a.credit for a in account_moves]),
                         Decimal('150.00'))

        # Open supplier invoices
        InvoiceLine = Model.get('account.invoice.line')
        set_user(purchase_user)
        purchase.reload()
        Invoice = Model.get('account.invoice')
        invoice1 = Invoice()
        invoice1.type = 'in'
        invoice1.party = purchase.party
        set_user(account_user)
        invoice1.invoice_date = today
        invoice_lines = sorted(purchase.invoice_lines, key=lambda l: l.id)
        invoice1.lines.append(InvoiceLine(invoice_lines[0].id))
        invoice1.lines.append(InvoiceLine(invoice_lines[1].id))
        invoice1.save()
        set_user(account_user)
        Invoice.post([invoice1.id], config.context)
        account_moves = AccountMoveLine.find([
            ('move_origin', '=', 'purchase.purchase,' + str(purchase.id)),
            ('account', '=', pending_payable.id),
        ])
        self.assertEqual(sum(l.debit - l.credit for l in account_moves),
                         Decimal('-120.00'))
        invoice2 = Invoice()
        invoice2.type = 'in'
        invoice2.party = purchase.party
        invoice2.invoice_date = today
        invoice2.lines.append(InvoiceLine(invoice_lines[2].id))
        invoice2.lines.append(InvoiceLine(invoice_lines[3].id))
        invoice2.save()
        Invoice.post([invoice2.id], config.context)
        account_moves = AccountMoveLine.find([
            ('move_origin', '=', 'purchase.purchase,' + str(purchase.id)),
            ('account', '=', pending_payable.id),
        ])
        self.assertEqual(sum(l.debit - l.credit for l in account_moves),
                         Decimal('0.00'))
        self.assertEqual(
            all(a.reconciliation is not None for a in account_moves), True)

        # Purchase products and invoice with diferent amount
        set_user(purchase_user)
        Purchase = Model.get('purchase.purchase')
        purchase = Purchase()
        purchase.party = supplier
        purchase.payment_term = payment_term
        purchase_line = purchase.lines.new()
        purchase_line.product = product1
        purchase_line.quantity = 20.0
        purchase_line.unit_price = product1.cost_price
        purchase.click('quote')
        purchase.click('confirm')
        self.assertEqual(purchase.state, 'processing')
        purchase.reload()
        self.assertEqual(len(purchase.moves), 1)

        self.assertEqual(len(purchase.shipment_returns), 0)

        self.assertEqual(len(purchase.invoices), 0)
        moves = purchase.moves
        set_user(stock_user)
        Move = Model.get('stock.move')
        ShipmentIn = Model.get('stock.shipment.in')
        shipment = ShipmentIn()
        shipment.supplier = supplier
        for move in moves:

            incoming_move = Move(id=move.id)

            shipment.incoming_moves.append(incoming_move)
        shipment.save()
        ShipmentIn.receive([shipment.id], config.context)
        ShipmentIn.do([shipment.id], config.context)
        set_user(purchase_user)
        purchase.reload()
        Invoice = Model.get('account.invoice')
        invoice = Invoice()
        invoice.type = 'in'
        invoice.party = purchase.party
        set_user(account_user)
        invoice.invoice_date = today
        invoice.lines.append(InvoiceLine(purchase.invoice_lines[0].id))
        invoice.save()
        line, = invoice.lines
        line.unit_price = Decimal('14.0')
        line.save()
        Invoice.post([invoice.id], config.context)

        # Create a Return
        config.user = purchase_user.id
        return_ = Purchase()
        return_.party = customer
        return_.payment_term = payment_term
        return_line = return_.lines.new()
        return_line.product = product1
        return_line.quantity = -4.
        return_line.unit_price = product1.cost_price
        return_line = return_.lines.new()
        return_line.type = 'comment'
        return_line.description = 'Comment'
        return_.click('quote')
        return_.click('confirm')
        self.assertEqual(return_.state, 'processing')
        return_.reload()
        self.assertEqual(len(return_.shipments), 0)

        self.assertEqual(len(return_.shipment_returns), 1)

        self.assertEqual(len(return_.invoices), 0)

        # Check Return Shipments
        set_user(purchase_user)
        ship_return, = return_.shipment_returns
        set_user(stock_user)
        ShipmentReturn = Model.get('stock.shipment.in.return')
        self.assertEqual(ship_return.state, 'waiting')
        move_return, = ship_return.moves
        self.assertEqual(move_return.product.rec_name, 'product')
        self.assertEqual(move_return.quantity, 4.0)
        ShipmentReturn.assign_try([ship_return.id], config.context)
        ShipmentReturn.do([ship_return.id], config.context)
        ship_return.reload()
        set_user(account_user)
        account_moves = AccountMoveLine.find([
            ('move_origin', '=', 'purchase.purchase,' + str(return_.id)),
            ('account', '=', pending_payable.id),
        ])
        self.assertEqual(len(account_moves), 1)
        self.assertEqual(sum([a.debit for a in account_moves]),
                         Decimal('40.00'))

        # Open customer credit note
        set_user(purchase_user)
        return_.reload()
        credit_note = Invoice()
        credit_note.type = 'in'
        credit_note.party = return_.party
        set_user(account_user)
        credit_note.invoice_date = today
        credit_note.lines.append(InvoiceLine(return_.invoice_lines[0].id))
        credit_note.save()
        set_user(account_user)
        self.assertEqual(credit_note.type, 'in')
        self.assertEqual(len(credit_note.lines), 1)
        self.assertEqual(sum(l.quantity for l in credit_note.lines), -4.0)
        credit_note.invoice_date = today
        credit_note.save()
        credit_note.click('post')
        account_moves = AccountMoveLine.find([
            ('reconciliation', '=', None),
            ('move_origin', '=', 'purchase.purchase,' + str(return_.id)),
            ('account', '=', pending_payable.id),
        ])
        self.assertEqual(len(account_moves), 0)

        # Create new purchase, shipment and invoice
        set_user(purchase_user)
        Purchase = Model.get('purchase.purchase')
        purchase = Purchase()
        purchase.party = supplier
        purchase.payment_term = payment_term
        purchase_line = purchase.lines.new()
        purchase_line.product = product1
        purchase_line.quantity = 50.0
        purchase_line.unit_price = product1.cost_price
        purchase.click('quote')
        purchase.click('confirm')
        self.assertEqual(purchase.state, 'processing')
        purchase.reload()
        self.assertEqual(len(purchase.moves), 1)

        self.assertEqual(len(purchase.shipment_returns), 0)

        self.assertEqual(len(purchase.invoices), 0)
        moves = purchase.moves
        set_user(stock_user)
        Move = Model.get('stock.move')
        ShipmentIn = Model.get('stock.shipment.in')
        shipment = ShipmentIn()
        shipment.supplier = supplier
        for move in moves:

            incoming_move = Move(id=move.id)

            shipment.incoming_moves.append(incoming_move)
        shipment.effective_date = today + datetime.timedelta(days=1)
        shipment.save()
        with self.assertRaises(MoveFutureWarning):

            try:

                shipment.click('receive')

            except MoveFutureWarning as warning:

                _, (key, *_) = warning.args

                raise
        Warning = Model.get('res.user.warning')
        Warning.skip(key, True, config.context)
        shipment.click('receive')
        with self.assertRaises(MoveFutureWarning):

            try:

                shipment.click('do')

            except MoveFutureWarning as warning:

                _, (key, *_) = warning.args

                raise
        Warning.skip(key, True, config.context)
        shipment.click('do')
        set_user(account_user)
        account_moves = AccountMoveLine.find([
            ('move_origin', '=', 'purchase.purchase,' + str(purchase.id)),
            ('account', '=', pending_payable.id),
        ])
        self.assertEqual(len(account_moves), 1)
        self.assertEqual(sum([a.debit - a.credit for a in account_moves]),
                         Decimal('-500.00'))
        InvoiceLine = Model.get('account.invoice.line')
        set_user(purchase_user)
        purchase.reload()
        Invoice = Model.get('account.invoice')
        invoice = Invoice()
        invoice.type = 'in'
        invoice.party = purchase.party
        set_user(account_user)
        invoice.invoice_date = today + datetime.timedelta(days=2)
        invoice.lines.append(InvoiceLine(purchase.invoice_lines[0].id))
        invoice.save()
        set_user(account_user)
        Invoice.post([invoice.id], config.context)
        account_moves = AccountMoveLine.find([
            ('move_origin', '=', 'purchase.purchase,' + str(purchase.id)),
            ('account', '=', pending_payable.id),
        ])
        self.assertEqual(len(account_moves), 2)
        self.assertEqual(sum(l.debit - l.credit for l in account_moves),
                         Decimal('0.00'))

        # Cancel invoice
        Invoice.cancel([invoice.id], config.context)
        set_user(purchase_user)
        purchase.reload()
        self.assertEqual(purchase.invoice_state, 'paid')
        set_user(account_user)
        account_moves = AccountMoveLine.find([
            ('move_origin', '=', 'purchase.purchase,' + str(purchase.id)),
            ('account', '=', pending_payable.id),
        ])
        self.assertEqual(len(account_moves), 3)
        self.assertEqual(sum(l.debit - l.credit for l in account_moves),
                         Decimal('-500.00'))

        # Execute wizard to recreate invoice line
        set_user(purchase_user)
        handler = Wizard('purchase.handle.invoice.exception', models=[purchase])
        handler.form.recreate_invoices.extend(handler.form.recreate_invoices.find())
        handler.execute('handle')
        purchase.reload()
        self.assertEqual(len(purchase.invoices_recreated), 1)

        set_user(account_user)
        account_moves = AccountMoveLine.find([
            ('move_origin', '=', 'purchase.purchase,' + str(purchase.id)),
            ('account', '=', pending_payable.id),
        ])
        self.assertEqual(len(account_moves), 4)
        self.assertEqual(
            sum(l.debit - l.credit for l in account_moves) == Decimal('0.00'),
            True)

        # Create new invoice with the recreated invoice lines and cancel it
        set_user(purchase_user)
        purchase.reload()

        Invoice = Model.get('account.invoice')
        InvoiceLine = Model.get('account.invoice.line')

        invoice1, invoice2 = purchase.invoices
        self.assertEqual((invoice1.state, invoice2.state), ('cancelled', 'draft'))

        set_user(account_user)
        invoice2.invoice_date = today + datetime.timedelta(days=3)
        invoice2.save()
        Invoice.post([invoice2.id], config.context)
        account_moves = AccountMoveLine.find([
            ('move_origin', '=', 'purchase.purchase,' + str(purchase.id)),
            ('account', '=', pending_payable.id),
        ])
        self.assertEqual(len(account_moves), 4)
        self.assertEqual(sum(l.debit - l.credit for l in account_moves),
                         Decimal('0.00'))
        Invoice.cancel([invoice2.id], config.context)
        set_user(purchase_user)
        purchase.reload()
        self.assertEqual(purchase.invoice_state, 'paid')
        set_user(account_user)
        account_moves = AccountMoveLine.find([
            ('move_origin', '=', 'purchase.purchase,' + str(purchase.id)),
            ('account', '=', pending_payable.id),
        ])
        self.assertEqual(len(account_moves), 5)
        self.assertEqual(sum(l.debit - l.credit for l in account_moves),
                         Decimal('-500.00'))

        # Execute wizard to ignore invoice line
        set_user(purchase_user)
        handler = Wizard('purchase.handle.invoice.exception', models=[purchase])
        handler.form.recreate_invoices.clear()
        handler.execute('handle')
        set_user(account_user)
        account_moves = AccountMoveLine.find([
            ('move_origin', '=', 'purchase.purchase,' + str(purchase.id)),
            ('account', '=', pending_payable.id),
        ])
        self.assertEqual(len(account_moves), 6)
        self.assertEqual(sum(l.debit - l.credit for l in account_moves),
                         Decimal('0.00'))

        # Check account moves dates
        sorted_moves = sorted(account_moves, key=lambda m: (m.date, m.amount))
        tomorrow = (today + datetime.timedelta(days=1)).strftime('%d/%m/%y')
        past_tomorrow = (today +
                         datetime.timedelta(days=2)).strftime('%d/%m/%y')
        past_3_days = (today + datetime.timedelta(days=3)).strftime('%d/%m/%y')
        got = [(move.date.strftime('%d/%m/%y'), move.debit - move.credit)
               for move in sorted_moves]
        expected = [
            (tomorrow, Decimal('-500.00')),
            (tomorrow, Decimal('500.00')),
            (past_tomorrow, Decimal('-500.00')),
            (past_tomorrow, Decimal('500.00')),
            (past_3_days, Decimal('-500.00')),
            (past_3_days, Decimal('500.00')),
        ]
        self.assertEqual(got, expected)
