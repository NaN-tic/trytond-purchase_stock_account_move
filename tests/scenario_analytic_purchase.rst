=================
Purchase Scenario
=================

"""
Create a purchase, with method invoice on shipment, and process it.
Create it's shipment and post it. After post will create automatically for each
move an account move with lines related to Pending Invoices accounts.
Post the invoice related to that purchase. That post create an acount move to
reconcile the Pending Invoice account move created before with the stock moves
post. If the quantity are not the same reconcile the existent move
and create new account move line, in the same account move, with the rest of
amount. Leaving the not invoice quantites pending to reconcile.
If you received the purchase quantities in 2 different shipments, the amount of
Pending Invoices accounts will be acumulated in the same account move.

The same process with negative purchase.

On refund that invoice don't do anyting. (not implemented on test)
"""

Imports::

    >>> import datetime
    >>> from dateutil.relativedelta import relativedelta
    >>> from decimal import Decimal
    >>> from operator import attrgetter
    >>> from proteus import config, Model, Wizard
    >>> from trytond.tests.tools import activate_modules
    >>> from trytond.modules.company.tests.tools import create_company, \
    ...     get_company
    >>> from trytond.modules.account.tests.tools import create_fiscalyear, \
    ...     create_chart, get_accounts
    >>> from trytond.modules.account_invoice.tests.tools import \
    ...     set_fiscalyear_invoice_sequences, create_payment_term
    >>> today = datetime.date.today()

Activate purchase_stock_account_move::

    >>> config = activate_modules(['purchase_stock_account_move',
    ...         'analytic_purchase'])

Create company::

    >>> _ = create_company()
    >>> company = get_company()

Reload the context::

    >>> User = Model.get('res.user')
    >>> Group = Model.get('res.group')
    >>> config._context = User.get_preferences(True, config.context)

Create purchase user::

    >>> purchase_user = User()
    >>> purchase_user.name = 'Purchase'
    >>> purchase_user.login = 'purchase'
    >>> purchase_user.main_company = company
    >>> purchase_group, = Group.find([('name', '=', 'Purchase')])
    >>> purchase_user.groups.append(purchase_group)
    >>> purchase_user.save()

Create stock user::

    >>> stock_user = User()
    >>> stock_user.name = 'Stock'
    >>> stock_user.login = 'stock'
    >>> stock_user.main_company = company
    >>> stock_group, = Group.find([('name', '=', 'Stock')])
    >>> stock_user.groups.append(stock_group)
    >>> stock_user.save()

Create account user::

    >>> account_user = User()
    >>> account_user.name = 'Account'
    >>> account_user.login = 'account'
    >>> account_user.main_company = company
    >>> account_group, = Group.find([('name', '=', 'Account')])
    >>> account_user.groups.append(account_group)
    >>> account_user.save()

Create fiscal year::

    >>> fiscalyear = set_fiscalyear_invoice_sequences(
    ...     create_fiscalyear(company))
    >>> fiscalyear.click('create_period')

Create chart of accounts::

    >>> _ = create_chart(company)
    >>> accounts = get_accounts(company)
    >>> receivable = accounts['receivable']
    >>> payable = accounts['payable']
    >>> revenue = accounts['revenue']
    >>> expense = accounts['expense']

Create pending account::

    >>> Account = Model.get('account.account')
    >>> pending_payable = Account()
    >>> pending_payable.code = 'PR'
    >>> pending_payable.name = 'Pending payable'
    >>> pending_payable.type = payable.type
    >>> pending_payable.kind = 'payable'
    >>> pending_payable.reconcile = True
    >>> pending_payable.parent = payable.parent
    >>> pending_payable.save()

Create analytic accounts::

    >>> AnalyticAccount = Model.get('analytic_account.account')
    >>> root = AnalyticAccount(type='root', name='Root')
    >>> root.save()
    >>> analytic_account = AnalyticAccount(root=root, parent=root,
    ...     name='Analytic', display_balance='debit-credit')
    >>> analytic_account.save()

Configure purchase to track pending_payables in accounting::

    >>> PurchaseConfig = Model.get('purchase.configuration')
    >>> purchase_config = PurchaseConfig(1)
    >>> purchase_config.purchase_shipment_method = 'order'
    >>> purchase_config.purchase_invoice_method = 'shipment'
    >>> purchase_config.pending_invoice_account = pending_payable
    >>> purchase_config.save()

Create parties::

    >>> Party = Model.get('party.party')
    >>> supplier = Party(name='Supplier')
    >>> supplier.save()
    >>> customer = Party(name='Customer')
    >>> customer.save()

Create category::

    >>> ProductCategory = Model.get('product.category')
    >>> category = ProductCategory(name='Category')
    >>> category.save()

Create products::

    >>> ProductUom = Model.get('product.uom')
    >>> unit, = ProductUom.find([('name', '=', 'Unit')])
    >>> ProductTemplate = Model.get('product.template')
    >>> Product = Model.get('product.product')
    >>> product1 = Product()
    >>> template1 = ProductTemplate()
    >>> template1.name = 'product'
    >>> template1.category = category
    >>> template1.default_uom = unit
    >>> template1.type = 'goods'
    >>> template1.purchasable = True
    >>> template1.salable = True
    >>> template1.list_price = Decimal('20')
    >>> template1.cost_price = Decimal('15')
    >>> template1.cost_price_method = 'fixed'
    >>> template1.account_expense = expense
    >>> template1.account_revenue = revenue
    >>> template1.save()
    >>> product1.template = template1
    >>> product1.save()
    >>> template2 = ProductTemplate()
    >>> template2.name = 'product'
    >>> template2.category = category
    >>> template2.default_uom = unit
    >>> template2.type = 'goods'
    >>> template2.purchasable = True
    >>> template2.salable = True
    >>> template2.list_price = Decimal('40')
    >>> template2.cost_price = Decimal('25')
    >>> template2.cost_price_method = 'fixed'
    >>> template2.account_expense = expense
    >>> template2.account_revenue = revenue
    >>> template2.save()
    >>> product2 = Product()
    >>> product2.template = template2
    >>> product2.save()

Create payment term::

    >>> payment_term = create_payment_term()
    >>> payment_term.save()

Create an Inventory::

    >>> config.user = stock_user.id
    >>> Inventory = Model.get('stock.inventory')
    >>> InventoryLine = Model.get('stock.inventory.line')
    >>> Location = Model.get('stock.location')
    >>> storage, = Location.find([
    ...         ('code', '=', 'STO'),
    ...         ])
    >>> inventory = Inventory()
    >>> inventory.location = storage
    >>> inventory.save()
    >>> inventory_line = InventoryLine(product=product1, inventory=inventory)
    >>> inventory_line.quantity = 100.0
    >>> inventory_line.expected_quantity = 0.0
    >>> inventory.save()
    >>> inventory_line.save()
    >>> inventory_line = InventoryLine(product=product2, inventory=inventory)
    >>> inventory_line.quantity = 100.0
    >>> inventory_line.expected_quantity = 0.0
    >>> inventory.save()
    >>> inventory_line.save()
    >>> Inventory.confirm([inventory.id], config.context)
    >>> inventory.state
    u'done'

Purchase products::

    >>> config.user = purchase_user.id
    >>> Purchase = Model.get('purchase.purchase')
    >>> purchase = Purchase()
    >>> purchase.party = supplier
    >>> purchase.payment_term = payment_term
    >>> purchase_line = purchase.lines.new()
    >>> purchase_line.product = product1
    >>> purchase_line.quantity = 20.0
    >>> entry, = purchase_line.analytic_accounts
    >>> entry.account = analytic_account
    >>> purchase_line = purchase.lines.new()
    >>> purchase_line.type = 'comment'
    >>> purchase_line.description = 'Comment'
    >>> purchase_line = purchase.lines.new()
    >>> purchase_line.product = product2
    >>> purchase_line.quantity = 20.0
    >>> entry, = purchase_line.analytic_accounts
    >>> entry.account = analytic_account
    >>> purchase.click('quote')
    >>> purchase.click('confirm')
    >>> purchase.click('process')
    >>> purchase.state
    u'processing'
    >>> purchase.reload()
    >>> len(purchase.moves), len(purchase.shipment_returns), len(purchase.invoices)
    (2, 0, 0)
    >>> config.user = account_user.id
    >>> AccountMoveLine = Model.get('account.move.line')
    >>> moves = AccountMoveLine.find([
    ...     ('account', '=', pending_payable.id)
    ...     ])
    >>> len(moves)
    0
    >>> analytic_account.reload()
    >>> analytic_account.debit
    Decimal('0.0')

Validate Shipments::

    >>> moves = purchase.moves
    >>> config.user = stock_user.id
    >>> Move = Model.get('stock.move')
    >>> ShipmentIn = Model.get('stock.shipment.in')
    >>> shipment = ShipmentIn()
    >>> shipment.supplier = supplier
    >>> for move in moves:
    ...     incoming_move = Move(id=move.id)
    ...     incoming_move.quantity = 15.0
    ...     shipment.incoming_moves.append(incoming_move)
    >>> shipment.save()
    >>> ShipmentIn.receive([shipment.id], config.context)
    >>> ShipmentIn.done([shipment.id], config.context)
    >>> config.user = account_user.id
    >>> account_moves = AccountMoveLine.find([
    ...     ('origin', '=', 'purchase.purchase,' + str(purchase.id)),
    ...     ('account', '=', pending_payable.id),
    ...     ])
    >>> len(account_moves)
    1
    >>> sum([a.credit for a in account_moves])
    Decimal('600.00')
    >>> account_moves = AccountMoveLine.find([
    ...     ('origin', '=', 'purchase.purchase,' + str(purchase.id)),
    ...     ('account.code', '=', 'E1'),
    ...     ])
    >>> len(account_moves)
    1
    >>> sum([a.debit for a in account_moves])
    Decimal('225.00')
    >>> account_moves = AccountMoveLine.find([
    ...     ('origin', '=', 'purchase.purchase,' + str(purchase.id)),
    ...     ('account.code', '=', 'E2'),
    ...     ])
    >>> len(account_moves)
    1
    >>> sum([a.debit for a in account_moves])
    Decimal('375.00')
    >>> analytic_account.reload()
    >>> analytic_account.debit
    Decimal('600.00')
    >>> config.user = purchase_user.id
    >>> purchase.reload()
    >>> moves = purchase.moves.find([('state', '=', 'draft')])
    >>> config.user = stock_user.id
    >>> shipment = ShipmentIn()
    >>> shipment.supplier = supplier
    >>> for move in moves:
    ...     incoming_move = Move(id=move.id)
    ...     shipment.incoming_moves.append(incoming_move)
    >>> shipment.save()
    >>> ShipmentIn.receive([shipment.id], config.context)
    >>> ShipmentIn.done([shipment.id], config.context)
    >>> config.user = account_user.id
    >>> account_moves = AccountMoveLine.find([
    ...     ('origin', '=', 'purchase.purchase,' + str(purchase.id)),
    ...     ('account', '=', pending_payable.id),
    ...     ])
    >>> len(account_moves)
    2
    >>> sum([a.credit for a in account_moves])
    Decimal('800.00')
    >>> account_moves = AccountMoveLine.find([
    ...     ('origin', '=', 'purchase.purchase,' + str(purchase.id)),
    ...     ('account.code', '=', 'E1'),
    ...     ])
    >>> len(account_moves)
    2
    >>> sum([a.debit for a in account_moves])
    Decimal('300.00')
    >>> account_moves = AccountMoveLine.find([
    ...     ('origin', '=', 'purchase.purchase,' + str(purchase.id)),
    ...     ('account.code', '=', 'E2'),
    ...     ])
    >>> len(account_moves)
    2
    >>> sum([a.debit for a in account_moves])
    Decimal('500.00')
    >>> analytic_account.reload()
    >>> analytic_account.debit
    Decimal('800.00')

Open supplier invoices::

    >>> config.user = purchase_user.id
    >>> purchase.reload()
    >>> Invoice = Model.get('account.invoice')
    >>> invoice1, invoice2 = purchase.invoices
    >>> config.user = account_user.id
    >>> invoice1.invoice_date = today
    >>> invoice1.save()
    >>> Invoice.post([invoice1.id], config.context)
    >>> account_moves = AccountMoveLine.find([
    ...     ('origin', '=', 'purchase.purchase,' + str(purchase.id)),
    ...     ('account', '=', pending_payable.id),
    ...     ('reconciliation', '=', None),
    ...     ])
    >>> line, = account_moves
    >>> line.credit
    Decimal('200.00')
    >>> account_moves = AccountMoveLine.find([
    ...     ('account.code', '=', 'E1'),
    ...     ])
    >>> sum([a.debit - a.credit for a in account_moves])
    Decimal('300.00')
    >>> account_moves = AccountMoveLine.find([
    ...     ('account.code', '=', 'E2'),
    ...     ])
    >>> sum([a.debit - a.credit for a in account_moves])
    Decimal('500.00')
    >>> analytic_account.reload()
    >>> analytic_account.balance
    Decimal('800.00')
    >>> invoice2.invoice_date = today
    >>> invoice2.save()
    >>> Invoice.post([invoice2.id], config.context)
    >>> account_moves = AccountMoveLine.find([
    ...     ('origin', '=', 'purchase.purchase,' + str(purchase.id)),
    ...     ('account', '=', pending_payable.id),
    ...     ])
    >>> sum(l.debit - l.credit for l in account_moves)
    Decimal('0.00')
    >>> all(a.reconciliation is not None for a in account_moves)
    True
    >>> account_moves = AccountMoveLine.find([
    ...     ('account.code', '=', 'E1'),
    ...     ])
    >>> sum([a.debit - a.credit for a in account_moves])
    Decimal('300.00')
    >>> account_moves = AccountMoveLine.find([
    ...     ('account.code', '=', 'E2'),
    ...     ])
    >>> sum([a.debit - a.credit for a in account_moves])
    Decimal('500.00')
    >>> analytic_account.reload()
    >>> analytic_account.balance
    Decimal('800.00')
