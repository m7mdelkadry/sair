from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.tools import float_is_zero


class SairTrip(models.Model):
    _name = 'sair.trip'
    _description = 'رحلة يومية - السير المتصل'
    _order = 'trip_date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # ── تعريف الحقول ─────────────────────────────────────────────────────────

    name = fields.Char(
        string='رقم الرحلة', required=True, copy=False, readonly=True,
        index='trigram',
        default=lambda self: self.env['ir.sequence'].next_by_code('sair.trip'),
    )
    trip_date = fields.Date(
        string='تاريخ الرحلة', required=True, index=True,
        default=fields.Date.context_today,
    )
    trip_type = fields.Selection(
        selection=[
            ('trip_jeddah', 'ترب - جدة'),
            ('trip_local', 'ترب - محلي'),
            ('other', 'أخرى'),
        ],
        string='نوع الرحلة', required=True, default='trip_local',
    )
    trip_amount = fields.Float(
        string='قيمة الرحلة (SAR)', required=True, digits=(10, 2),
    )
    description = fields.Char(string='ملاحظة / وصف الرحلة')

    # ── السائق ───────────────────────────────────────────────────────────────

    driver_type = fields.Selection(
        selection=[
            ('internal', 'سائق داخلي - موظف'),
            ('external', 'سائق خارجي - 50/50'),
            ('commission', 'سائق بالعمولة'),
        ],
        string='نوع السائق', required=True, index=True, tracking=True,
    )
    employee_id = fields.Many2one(
        'hr.employee', string='السائق (موظف)',
        index=True, ondelete='restrict',
    )
    partner_id = fields.Many2one(
        'res.partner', string='السائق (خارجي / عمولة)',
        index=True, ondelete='restrict',
    )
    driver_display = fields.Char(
        string='السائق',
        compute='_compute_driver_display', store=True, index='trigram',
    )

    # ── العمولة (تظهر فقط لـ commission) ─────────────────────────────────────

    company_commission = fields.Float(
        string='عمولة الشركة (SAR)', digits=(10, 2), tracking=True,
    )
    office_commission = fields.Float(
        string='عمولة المكتب (SAR)', digits=(10, 2), tracking=True,
    )
    driver_commission = fields.Float(
        string='عمولة السائق (SAR)', digits=(10, 2), tracking=True,
    )

    # ── العميل ───────────────────────────────────────────────────────────────

    customer_id = fields.Many2one(
        'res.partner', string='العميل',
        index=True, ondelete='restrict',
        domain=[('customer_rank', '>', 0)],
    )

    # ── السيارة ومركز التكلفة ─────────────────────────────────────────────────

    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='السيارة', required=True, index=True, ondelete='restrict',
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='مركز التكلفة',
        compute='_compute_analytic_account', store=True, readonly=False, index=True,
    )

    # ── الكاش والعهدة ─────────────────────────────────────────────────────────

    cash_collected = fields.Boolean(
        string='السائق حصّل نقدي؟', default=False, tracking=True,
    )
    amana_id = fields.Many2one(
        'sair.amana', string='العهدة', readonly=True, copy=False, ondelete='set null',
    )

    # ── الفاتورة ─────────────────────────────────────────────────────────────

    invoice_id = fields.Many2one(
        'account.move', string='الفاتورة', readonly=True, copy=False,
        ondelete='set null', domain=[('move_type', '=', 'out_invoice')],
    )
    has_invoice = fields.Boolean(
        string='عندها فاتورة؟', compute='_compute_has_invoice', store=True,
    )

    # ── التسوية والحالة ───────────────────────────────────────────────────────

    settlement_id = fields.Many2one(
        'sair.settlement', string='التسوية', readonly=True, copy=False,
        index=True, ondelete='set null',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('confirmed', 'مؤكدة'),
            ('settled', 'مُسوَّاة'),
        ],
        string='الحالة', default='draft', required=True, tracking=True, index=True,
    )

    # ── حقول محسوبة ───────────────────────────────────────────────────────────

    driver_share = fields.Float(string='حصة السائق (SAR)', compute='_compute_shares', store=True, digits=(10, 2))
    company_share = fields.Float(string='حصة الشركة (SAR)', compute='_compute_shares', store=True, digits=(10, 2))
    month_year = fields.Char(string='الشهر/السنة', compute='_compute_month_year', store=True, index=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)

    # ── حقول المتبقي (لتوزيع العمولات والمصاريف) ────────────────────────────

    remaining_for_commissions = fields.Float(
        string='المتبقي من قيمة الرحلة',
        compute='_compute_remaining_commissions', digits=(10, 2),
        help='قيمة الرحلة - عمولة الشركة - عمولة المكتب - عمولة السائق = لازم تكون صفر',
    )

    # ── حقول السمارت بوتن ──────────────────────────────────────────────────

    expense_count = fields.Integer(string='عدد المصاريف', compute='_compute_expense_stats')
    trip_expenses_total = fields.Float(string='مصاريف الرحلة', compute='_compute_expense_stats')
    trip_net = fields.Float(string='صافي ربح الشركة', compute='_compute_expense_stats', digits=(10, 2))

    # ── Compute Methods ───────────────────────────────────────────────────────

    @api.depends('trip_amount', 'driver_type', 'company_commission', 'driver_commission')
    def _compute_shares(self):
        for rec in self:
            if rec.driver_type == 'external':
                rec.driver_share = rec.trip_amount * 0.50
                rec.company_share = rec.trip_amount * 0.50
            elif rec.driver_type == 'commission':
                rec.driver_share = rec.driver_commission
                rec.company_share = rec.company_commission
            else:
                rec.driver_share = 0.0
                rec.company_share = rec.trip_amount

    @api.depends('trip_amount', 'company_commission', 'driver_commission', 'office_commission', 'driver_type')
    def _compute_remaining_commissions(self):
        """المتبقي من قيمة الرحلة بعد توزيع العمولات الثلاث."""
        for rec in self:
            if rec.driver_type == 'commission':
                rec.remaining_for_commissions = (
                    rec.trip_amount
                    - rec.company_commission
                    - rec.office_commission
                    - rec.driver_commission
                )
            else:
                rec.remaining_for_commissions = 0.0

    @api.depends('partner_id', 'driver_type')
    def _compute_driver_display(self):
        for rec in self:
            if rec.partner_id:
                rec.driver_display = rec.partner_id.name
            else:
                rec.driver_display = ''

    @api.depends('trip_date')
    def _compute_month_year(self):
        for rec in self:
            rec.month_year = rec.trip_date.strftime('%Y-%m') if rec.trip_date else ''

    @api.depends('invoice_id')
    def _compute_has_invoice(self):
        for rec in self:
            rec.has_invoice = bool(rec.invoice_id)

    # ═══════════════════════════════════════════════════════════════════════
    #  الأناليتك (يُسحب من الفليت فقط)
    # ═══════════════════════════════════════════════════════════════════════
    @api.depends('vehicle_id')
    def _compute_analytic_account(self):
        for rec in self:
            if rec.vehicle_id:
                if not rec.vehicle_id.analytic_account_id:
                    raise ValidationError(
                        'لا يوجد مركز تكلفة مسجل لهذه السيارة! '
                        'يرجى الذهاب لشاشة "السيارات" وإضافة مركز التكلفة أولاً.'
                    )
                rec.analytic_account_id = rec.vehicle_id.analytic_account_id
            else:
                rec.analytic_account_id = False

    def _compute_expense_stats(self):
        """إحصائيات المصاريف للسمارتبوتن فقط."""
        for rec in self:
            expenses = self.env['sair.driver.expense'].search([('trip_id', '=', rec.id)])
            rec.expense_count = len(expenses)
            rec.trip_expenses_total = sum(expenses.mapped('amount'))

            # صافي ربح الشركة (للسمارتبوتن)
            company_exp = sum(expenses.mapped('company_expense_share'))
            net = rec.trip_amount
            if rec.driver_type == 'internal':
                net -= rec.trip_expenses_total
            elif rec.driver_type == 'external':
                net -= rec.driver_share
                net -= company_exp
            elif rec.driver_type == 'commission':
                net -= rec.driver_commission
                net -= rec.office_commission
                net -= company_exp
            rec.trip_net = net

    def action_view_trip_expenses(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'مصاريف رحلة {self.name}',
            'res_model': 'sair.driver.expense',
            'view_mode': 'list,form',
            'domain': [('trip_id', '=', self.id)],
            'context': {
                'default_trip_id': self.id,
                'default_vehicle_id': self.vehicle_id.id,
                'default_driver_type': self.driver_type,
                'default_partner_id': self.partner_id.id if self.partner_id else False,
            }
        }

    # ── Onchange ─────────────────────────────────────────────────────────────

    @api.onchange('driver_type')
    def _onchange_driver_type(self):
        self.partner_id = False
        if self.driver_type != 'commission':
            self.company_commission = 0.0
            self.office_commission = 0.0
            self.driver_commission = 0.0

    # ── Create / Write ────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.cash_collected and not rec.amana_id:
                rec._create_amana()
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals.get('cash_collected'):
            for rec in self:
                if not rec.amana_id:
                    rec._create_amana()
        return res

    def _create_amana(self):
        amana = self.env['sair.amana'].create({
            'driver_type': self.driver_type,
            'partner_id': self.partner_id.id if self.partner_id else False,
            'vehicle_id': self.vehicle_id.id,
            'amana_date': self.trip_date,
            'amount': self.trip_amount,
            'trip_id': self.id,
            'notes': f'عهدة تلقائية — رحلة {self.name}',
            'state': 'pending',
        })
        self.amana_id = amana.id

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('trip_amount')
    def _check_trip_amount(self):
        for rec in self:
            if rec.trip_amount <= 0:
                raise ValidationError('قيمة الرحلة لازم تكون أكبر من صفر.')

    @api.constrains('driver_type', 'partner_id')
    def _check_driver(self):
        for rec in self:
            if not rec.partner_id:
                raise ValidationError('لازم تختار السائق.')
            if rec.driver_type in ('external', 'commission') and not rec.partner_id:
                raise ValidationError('السائق الخارجي / بالعمولة: اختر جهة اتصال.')

    @api.constrains('driver_type', 'company_commission', 'office_commission', 'driver_commission')
    def _check_commission(self):
        for rec in self:
            if rec.driver_type == 'commission':
                total = rec.company_commission + rec.office_commission + rec.driver_commission
                if total <= 0:
                    raise ValidationError('سائق بالعمولة: لازم تدخل قيمة عمولة واحدة على الأقل.')

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_confirm(self):
        prec = self.env['decimal.precision'].precision_get('Account')

        for rec in self:
            if rec.state != 'draft':
                raise ValidationError('الرحلة مش في حالة مسودة.')

            # ── فحص توزيع العمولات (للسائق بالعمولة فقط) ──
            if rec.driver_type == 'commission':
                if not float_is_zero(rec.remaining_for_commissions, precision_digits=2):
                    raise ValidationError(
                        f'المتبقي من قيمة الرحلة: {rec.remaining_for_commissions:.2f} SAR\n'
                        'لازم توزع قيمة الرحلة كاملة بين (عمولة الشركة + عمولة المكتب + عمولة السائق).\n'
                        f'القيمة المدخلة: {rec.company_commission + rec.office_commission + rec.driver_commission:.2f} '
                        f'من أصل {rec.trip_amount:.2f}'
                    )

            rec.state = 'confirmed'

            # إنشاء عمولة المكتب تلقائياً
            if rec.office_commission > 0:
                self.env['sair.office.commission'].create({
                    'commission_date': rec.trip_date,
                    'amount': rec.office_commission,
                    'trip_id': rec.id,
                    'vehicle_id': rec.vehicle_id.id if rec.vehicle_id else False,
                    'driver_display': rec.driver_display,
                    'notes': f'رحلة {rec.name}',
                    'company_id': rec.company_id.id,
                })

    def action_reset_draft(self):
        for rec in self:
            if rec.state == 'settled':
                raise ValidationError('الرحلة مُسوَّاة ومش ممكن ترجع مسودة.')
            rec.state = 'draft'

    def action_create_invoice(self):
        self.ensure_one()
        if not self.customer_id:
            raise ValidationError('لازم تحدد العميل أولاً قبل إنشاء الفاتورة.')
        if self.invoice_id:
            raise ValidationError('في فاتورة مرتبطة بالفعل — رقمها: %s' % self.invoice_id.name)

        product = self._get_delivery_product()
        analytic = {str(self.analytic_account_id.id): 100} if self.analytic_account_id else {}

        line_name = self.description if self.description else 'خدمة توصيل'

        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.customer_id.id,
            'invoice_date': self.trip_date,
            'ref': self.name,
            'narration': f'فاتورة خدمة توصيل — رحلة {self.name}',
            'company_id': self.company_id.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': product.id,
                'name': line_name,
                'quantity': 1,
                'price_unit': self.trip_amount,
                'analytic_distribution': analytic,
            })],
        })
        self.invoice_id = invoice.id
        self.message_post(
            body=f'تم إنشاء الفاتورة: <a href="/odoo/accounting/customer-invoices/{invoice.id}">{invoice.name or "مسودة"}</a>'
        )
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_invoice(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _get_delivery_product(self):
        tmpl = self.env['product.template'].search([
            ('name', '=', 'خدمة توصيل'), ('type', '=', 'service'),
        ], limit=1)
        if not tmpl:
            tmpl = self.env['product.template'].create({
                'name': 'خدمة توصيل', 'type': 'service', 'list_price': 0.0,
            })
        return tmpl.product_variant_id
