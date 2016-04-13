=================
Purchase Scenario
=================

Imports::

    >>> import datetime
    >>> from dateutil.relativedelta import relativedelta
    >>> from decimal import Decimal
    >>> from operator import attrgetter
    >>> from proteus import config, Model, Wizard
    >>> from trytond.modules.company.tests.tools import create_company, \
    ...     get_company
    >>> from trytond.modules.account.tests.tools import create_fiscalyear, \
    ...     create_chart, get_accounts
    >>> from trytond.modules.account_invoice.tests.tools import \
    ...     set_fiscalyear_invoice_sequences, create_payment_term
    >>> today = datetime.date.today()

Create database::

    >>> config = config.set_trytond()
    >>> config.pool.test = True

Install purchase::

    >>> Module = Model.get('ir.module')
    >>> module, = Module.find([('name', '=', 'purchase_stock_account_move')])
    >>> module.click('install')
    >>> Wizard('ir.module.install_upgrade').execute('upgrade')

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
    >>> revenue = accounts['revenue']
    >>> expense = accounts['expense']
    >>> payable = accounts['payable']

Create pending account and another expense account::

    >>> Account = Model.get('account.account')
    >>> pending_payable = Account()
    >>> pending_payable.code = 'PR'
    >>> pending_payable.name = 'Pending payable'
    >>> pending_payable.type = payable.type
    >>> pending_payable.kind = 'payable'
    >>> pending_payable.reconcile = True
    >>> pending_payable.parent = payable.parent
    >>> pending_payable.save()
    >>> expense.code = 'E1'
    >>> expense.save()
    >>> expense2 = Account()
    >>> expense2.code = 'E2'
    >>> expense2.name = 'Second expense'
    >>> expense2.type = expense.type
    >>> expense2.kind = 'expense'
    >>> expense2.parent = expense.parent
    >>> expense2.save()


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
    >>> template2.account_expense = expense2
    >>> template2.account_revenue = revenue
    >>> template2.save()
    >>> product2 = Product()
    >>> product2.template = template2
    >>> product2.save()
    >>> service_product = Product()
    >>> service_template = ProductTemplate()
    >>> service_template.name = 'product'
    >>> service_template.category = category
    >>> service_template.default_uom = unit
    >>> service_template.type = 'service'
    >>> service_template.purchasable = True
    >>> service_template.salable = True
    >>> service_template.list_price = Decimal('20')
    >>> service_template.cost_price = Decimal('15')
    >>> service_template.cost_price_method = 'fixed'
    >>> service_template.account_expense = expense
    >>> service_template.account_revenue = revenue
    >>> service_template.save()
    >>> service_product.template = service_template
    >>> service_product.save()

Create payment term::

    >>> payment_term = create_payment_term()
    >>> payment_term.save()

Purchase services::

    >>> config.user = purchase_user.id
    >>> AccountMoveLine = Model.get('account.move.line')
    >>> Purchase = Model.get('purchase.purchase')
    >>> purchase = Purchase()
    >>> purchase.party = supplier
    >>> purchase.payment_term = payment_term
    >>> purchase.invoice_method = 'order'
    >>> purchase_line = purchase.lines.new()
    >>> purchase_line.product = service_product
    >>> purchase_line.quantity = 2.0
    >>> purchase_line = purchase.lines.new()
    >>> purchase_line.type = 'comment'
    >>> purchase_line.description = 'Comment'
    >>> purchase.click('quote')
    >>> purchase.click('confirm')
    >>> purchase.click('process')
    >>> purchase.state
    u'processing'
    >>> purchase.reload()
    >>> len(purchase.shipments), len(purchase.shipment_returns), len(purchase.invoices)
    (0, 0, 1)
    >>> invoice, = purchase.invoices
    >>> invoice.origins == purchase.rec_name
    True
    >>> config.user = account_user.id
    >>> moves = AccountMoveLine.find([
    ...     ('account', '=', pending_payable.id)
    ...     ])
    >>> len(moves)
    0

Purchase products::

    >>> config.user = purchase_user.id
    >>> Purchase = Model.get('purchase.purchase')
    >>> purchase = Purchase()
    >>> purchase.party = supplier
    >>> purchase.payment_term = payment_term
    >>> purchase_line = purchase.lines.new()
    >>> purchase_line.product = product1
    >>> purchase_line.quantity = 20.0
    >>> purchase_line = purchase.lines.new()
    >>> purchase_line.type = 'comment'
    >>> purchase_line.description = 'Comment'
    >>> purchase_line = purchase.lines.new()
    >>> purchase_line.product = product2
    >>> purchase_line.quantity = 20.0
    >>> purchase.click('quote')
    >>> purchase.click('confirm')
    >>> purchase.click('process')
    >>> purchase.state
    u'processing'
    >>> purchase.reload()
    >>> len(purchase.moves), len(purchase.shipment_returns), len(purchase.invoices)
    (2, 0, 0)
    >>> config.user = account_user.id
    >>> moves = AccountMoveLine.find([
    ...     ('account', '=', pending_payable.id)
    ...     ])
    >>> len(moves)
    0
    True

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
    True

Open supplier invoices::

    >>> config.user = purchase_user.id
    >>> purchase.reload()
    >>> invoice1, invoice2 = purchase.invoices
    >>> config.user = account_user.id
    >>> Invoice = Model.get('account.invoice')
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
    True
    >>> account_moves = AccountMoveLine.find([
    ...     ('account.code', '=', 'E1'),
    ...     ])
    >>> sum([a.debit - a.credit for a in account_moves])
    Decimal('300.00')
    True
    >>> account_moves = AccountMoveLine.find([
    ...     ('account.code', '=', 'E2'),
    ...     ])
    >>> sum([a.debit - a.credit for a in account_moves])
    Decimal('500.00')
    True
    >>> invoice2.invoice_date = today
    >>> invoice2.save()
    >>> Invoice.post([invoice2.id], config.context)
    >>> AccountMoveLine = Model.get('account.move.line')
    >>> account_moves = AccountMoveLine.find([
    ...     ('origin', '=', 'purchase.purchase,' + str(purchase.id)),
    ...     ('account', '=', pending_payable.id),
    ...     ])
    >>> sum(l.debit - l.credit for l in account_moves)
    Decimal('0.00')
    True
    >>> all(a.reconciliation is not None for a in account_moves)
    True
    >>> account_moves = AccountMoveLine.find([
    ...     ('account.code', '=', 'E1'),
    ...     ])
    >>> sum([a.debit - a.credit for a in account_moves])
    Decimal('300.00')
    True
    >>> account_moves = AccountMoveLine.find([
    ...     ('account.code', '=', 'E2'),
    ...     ])
    >>> sum([a.debit - a.credit for a in account_moves])
    Decimal('500.00')
    True


Purchase products and invoice with diferent amount::

    >>> config.user = purchase_user.id
    >>> Purchase = Model.get('purchase.purchase')
    >>> purchase = Purchase()
    >>> purchase.party = supplier
    >>> purchase.payment_term = payment_term
    >>> purchase_line = purchase.lines.new()
    >>> purchase_line.product = product1
    >>> purchase_line.quantity = 20.0
    >>> purchase.click('quote')
    >>> purchase.click('confirm')
    >>> purchase.click('process')
    >>> purchase.state
    u'processing'
    >>> purchase.reload()
    >>> len(purchase.moves), len(purchase.shipment_returns), len(purchase.invoices)
    (1, 0, 0)
    >>> moves = purchase.moves
    >>> config.user = stock_user.id
    >>> Move = Model.get('stock.move')
    >>> ShipmentIn = Model.get('stock.shipment.in')
    >>> shipment = ShipmentIn()
    >>> shipment.supplier = supplier
    >>> for move in moves:
    ...     incoming_move = Move(id=move.id)
    ...     shipment.incoming_moves.append(incoming_move)
    >>> shipment.save()
    >>> ShipmentIn.receive([shipment.id], config.context)
    >>> ShipmentIn.done([shipment.id], config.context)
    >>> config.user = purchase_user.id
    >>> purchase.reload()
    >>> Invoice = Model.get('account.invoice')
    >>> invoice, = purchase.invoices
    >>> config.user = account_user.id
    >>> invoice.invoice_date = today
    >>> invoice.save()
    >>> line, = invoice.lines
    >>> line.unit_price = Decimal('14.0')
    >>> line.save()
    >>> Invoice.post([invoice.id], config.context)


Create a Return::

    >>> config.user = purchase_user.id
    >>> return_ = Purchase()
    >>> return_.party = customer
    >>> return_.payment_term = payment_term
    >>> return_line = return_.lines.new()
    >>> return_line.product = product1
    >>> return_line.quantity = -4.
    >>> return_line = return_.lines.new()
    >>> return_line.type = 'comment'
    >>> return_line.description = 'Comment'
    >>> return_.click('quote')
    >>> return_.click('confirm')
    >>> return_.click('process')
    >>> return_.state
    u'processing'
    >>> return_.reload()
    >>> (len(return_.shipments), len(return_.shipment_returns),
    ...     len(return_.invoices))
    (0, 1, 0)

Check Return Shipments::

    >>> config.user = purchase_user.id
    >>> ship_return, = return_.shipment_returns
    >>> config.user = stock_user.id
    >>> ShipmentReturn = Model.get('stock.shipment.in.return')
    >>> ship_return.state
    u'waiting'
    >>> move_return, = ship_return.moves
    >>> move_return.product.rec_name
    u'product'
    >>> move_return.quantity
    4.0
    >>> ShipmentReturn.assign_try([ship_return.id], config.context)
    True
    >>> ShipmentReturn.done([ship_return.id], config.context)
    >>> ship_return.reload()
    >>> config.user = account_user.id
    >>> account_moves = AccountMoveLine.find([
    ...     ('origin', '=', 'purchase.purchase,' + str(return_.id)),
    ...     ('account', '=', pending_payable.id),
    ...     ])
    >>> len(account_moves)
    1
    >>> sum([a.debit for a in account_moves])
    Decimal('60.00')

Open customer credit note::

    >>> config.user = purchase_user.id
    >>> return_.reload()
    >>> credit_note, = return_.invoices
    >>> config.user = account_user.id
    >>> credit_note.type
    u'in_credit_note'
    >>> len(credit_note.lines)
    1
    >>> sum(l.quantity for l in credit_note.lines)
    4.0
    >>> credit_note.invoice_date = today
    >>> credit_note.save()
    >>> Invoice.post([credit_note.id], config.context)
    >>> account_moves = AccountMoveLine.find([
    ...     ('reconciliation', '=', None),
    ...     ('origin', '=', 'purchase.purchase,' + str(return_.id)),
    ...     ('account', '=', pending_payable.id),
    ...     ])
    >>> len(account_moves)
    0
