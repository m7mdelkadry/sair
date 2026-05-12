from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.tools import float_is_zero


class SairDriverExpense(models.Model):
    _name = 'sair.driver.expense'
    _description = 'مصروف يومي - السير المتصل'
    _order = 'expense_date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='رقم المصروف', required=True, copy=False, readonly=True,
        index='trigram',
        default=lambda self: self.env['ir.sequence'].next_by_code('sair.driver.expense'),
    )
    expense_date = fields.Date(
        string='تاريخ المصروف', required=True, index=True,
        default=fields.Date.context_today,
    )
    driver_type = fields.Selection(
        selection=[
            ('internal',   'سائق داخلي'),
            ('external',   'سائق خارجي 50/50'),
            ('commission', 'سائق بالعمولة'),
        ],
        string='نوع السائق', required=True, index=True,
    )
    employee_id    = fields.Many2one('hr.employee', string='السائق (موظف)',         index=True, ondelete='restrict')
    partner_id     = fields.Many2one('res.partner', string='السائق (خارجي/عمولة)', index=True, ondelete='restrict')
    driver_display = fields.Char(string='السائق', compute='_compute_driver_display', store=True, index='trigram')
    vehicle_id     = fields.Many2one('fleet.vehicle', string='السيارة', required=True, index=True, ondelete='restrict')
    amount         = fields.Float(string='قيمة المصروف (SAR)', required=True, digits=(10, 2))
    trip_id = fields.Many2one('sair.trip', string='الرحلة', index=True, ondelete='restrict')
    expense_type   = fields.Selection(
        selection=[
            ('fuel',        'وقود'),
            ('toll',        'رسوم طريق'),
            ('maintenance', 'صيانة'),
            ('other',       'أخرى'),
        ],
        string='نوع المصروف', required=True, default='fuel', index=True,
    )
    description = fields.Char(string='بيان')

    # ── مركز التكلفة من السيارة تلقائياً ────────────────────────────────────
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='مركز التكلفة (السيارة)',
        compute='_compute_analytic', store=True, readonly=False,
    )

    # ── حساب المصروف (جديد) ──────────────────────────────────────────────────
    expense_account_id = fields.Many2one(
        'account.account',
        string='حساب المصروف',
        domain="[('account_type', '=', 'expense')]",
        ondelete='restrict',
        help='يُملأ تلقائياً عند اختيار نوع المصروف — يمكن التعديل',
        tracking=True,
    )

    # ── القيد المحاسبي ────────────────────────────────────────────────────────
    move_id = fields.Many2one(
        'account.move', string='القيد المحاسبي',
        readonly=True, copy=False, ondelete='set null',
    )

    settlement_id = fields.Many2one(
        'sair.settlement', string='التسوية',
        readonly=True, index=True, ondelete='set null',
    )
    state = fields.Selection(
        selection=[('draft', 'مسودة'), ('confirmed', 'مؤكد'), ('settled', 'مُسوَّى')],
        string='الحالة', default='draft', tracking=True, index=True,
    )
    month_year = fields.Char(
        string='الشهر/السنة', compute='_compute_month_year', store=True, index=True,
    )
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, index=True)

    # ── حصص المصروف ───────────────────────────────────────────────────────────
    driver_expense_share  = fields.Float(string='على السائق',  digits=(10, 2), default=0.0)
    company_expense_share = fields.Float(string='على الشركة', digits=(10, 2), default=0.0)

    # ── المتبقي من توزيع المصروف ─────────────────────────────────────────────
    remaining_expense = fields.Float(
        string='المتبقي من المصروف',
        compute='_compute_remaining_expense', digits=(10, 2),
        help='قيمة المصروف - على السائق - على الشركة = لازم تكون صفر',
    )

    # ── Compute ───────────────────────────────────────────────────────────────

    @api.depends('amount', 'driver_expense_share', 'company_expense_share', 'driver_type')
    def _compute_remaining_expense(self):
        """المتبقي من المصروف بعد التوزيع — لازم يكون صفر عشان التأكيد."""
        for rec in self:
            if rec.driver_type == 'internal':
                rec.remaining_expense = 0.0
            else:
                rec.remaining_expense = (
                    rec.amount
                    - rec.driver_expense_share
                    - rec.company_expense_share
                )

    @api.depends('vehicle_id', 'trip_id')
    def _compute_analytic(self):
        for rec in self:
            # لو المصروف مربوط برحلة، خد الأناليتك من الرحلة
            if rec.trip_id and rec.trip_id.analytic_account_id:
                rec.analytic_account_id = rec.trip_id.analytic_account_id
            elif rec.vehicle_id:
                rec.analytic_account_id = self._get_or_create_analytic(rec.vehicle_id)
            else:
                rec.analytic_account_id = False

    def _get_or_create_analytic(self, vehicle):
        AnalyticAccount = self.env['account.analytic.account']
        analytic = AnalyticAccount.search([
            ('name', '=', vehicle.name),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not analytic:
            plan = self.env['account.analytic.plan'].search([('name', '=', 'الأسطول - السير المتصل')], limit=1)
            if not plan:
                plan = self.env['account.analytic.plan'].create({'name': 'الأسطول - السير المتصل'})
            analytic = AnalyticAccount.create({
                'name': vehicle.name,
                'code': vehicle.license_plate or vehicle.name,
                'company_id': self.env.company.id,
                'plan_id': plan.id,
            })
        return analytic

    @api.depends('partner_id', 'driver_type')
    def _compute_driver_display(self):
        for rec in self:
            if rec.partner_id:
                rec.driver_display = rec.partner_id.name
            else:
                rec.driver_display = ''

    @api.depends('expense_date')
    def _compute_month_year(self):
        for rec in self:
            rec.month_year = rec.expense_date.strftime('%Y-%m') if rec.expense_date else ''

    # ── Onchange ─────────────────────────────────────────────────────────────

    @api.onchange('trip_id')
    def _onchange_trip_id(self):
        if self.trip_id:
            self.driver_type = self.trip_id.driver_type
            self.partner_id = self.trip_id.partner_id
            self.vehicle_id = self.trip_id.vehicle_id

    @api.onchange('driver_type')
    def _onchange_driver_type(self):
        self.partner_id = False

    @api.onchange('expense_type', 'company_id')
    def _onchange_expense_type(self):
        """اقتراح حساب المصروف تلقائياً — يمكن للمستخدم تغييره"""
        if not self.expense_account_id:
            account = self._find_expense_account()
            if account:
                self.expense_account_id = account

    # ── Helpers محاسبية ───────────────────────────────────────────────────────

    def _find_expense_account(self):
        """حساب مصاريف التشغيل من الإعدادات."""
        settings = self.env['sair.settings'].get_for_company(self.company_id.id)
        acc = settings.operating_expense_account_id
        if not acc:
            raise ValidationError(
                'لم يُحدد حساب مصاريف التشغيل في إعدادات السير المتصل. اذهب إلى: السير المتصل ← التهيئة ← الإعدادات'
            )
        return acc

    def _find_credit_account(self):
        """حساب ذمم دائنة مصاريف من الإعدادات."""
        settings = self.env['sair.settings'].get_for_company(self.company_id.id)
        acc = settings.expense_payable_account_id
        if not acc:
            raise ValidationError(
                'لم يُحدد حساب ذمم دائنة مصاريف في إعدادات السير المتصل. اذهب إلى: السير المتصل ← التهيئة ← الإعدادات'
            )
        return acc

    def _get_analytic_distribution(self):
        """بناء analytic_distribution dict للقيد المحاسبي"""
        if self.analytic_account_id:
            return {str(self.analytic_account_id.id): 100}
        return {}

    def _get_expense_journal(self):
        """يومية مصاريف التشغيل من الإعدادات."""
        settings = self.env['sair.settings'].get_for_company(self.company_id.id)
        journal = settings.operating_expense_journal_id
        if not journal:
            raise ValidationError(
                'لم تُحدد يومية مصاريف التشغيل في إعدادات السير المتصل. اذهب إلى: السير المتصل ← التهيئة ← الإعدادات'
            )
        return journal

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError('قيمة المصروف لازم تكون أكبر من صفر.')

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_confirm(self):
        """تأكيد المصروف: فحص التوزيع + إنشاء قيد محاسبي في الأناليتك."""
        prec = self.env['decimal.precision'].precision_get('Account')

        for rec in self:
            if rec.state == 'draft':
                # فحص توزيع المصروف (للخارجي والعمولة فقط)
                if rec.driver_type != 'internal':
                    if not float_is_zero(rec.remaining_expense, precision_digits=2):
                        raise ValidationError(
                            f'المتبقي من المصروف: {rec.remaining_expense:.2f} SAR\n' 'لازم توزع قيمة المصروف كاملة بين (على السائق + على الشركة).\n'
                            f'القيمة المدخلة: {rec.driver_expense_share + rec.company_expense_share:.2f} '
                            f'من أصل {rec.amount:.2f}'
                        )

                # ── إنشاء القيد المحاسبي ──────────────────────────────
                if not rec.move_id:
                    rec._create_expense_move()

                rec.state = 'confirmed'

    def _create_expense_move(self):
        """إنشاء قيد محاسبي للمصروف مع الأناليتك.
        القيد:
          DEBIT  حساب المصروف (fuel/toll/maintenance/other)  ← بقيمة المصروف كاملة + أناليتك
          CREDIT مستحقات / ذمم دائنة                        ← بقيمة المصروف كاملة
        """
        self.ensure_one()

        journal = self._get_expense_journal()

        # حساب المصروف (من الحقل المحدد أو أول حساب expense)
        if self.expense_account_id:
            debit_acc = self.expense_account_id
        else:
            debit_acc = self._find_expense_account()

        if not debit_acc:
            raise ValidationError(
                'لا يوجد حساب مصروف (expense) للشركة.\n' 'راجع: محاسبة ← دليل الحسابات.'
            )

        credit_acc = self._find_credit_account()
        if not credit_acc:
            raise ValidationError(
                'لا يوجد حساب ذمم دائنة (liability_payable) للشركة.\n' 'راجع: محاسبة ← دليل الحسابات.'
            )

        # الأناليتك: فقط للسائق الموظف — للخارجي/العمولة ستُسجَّل في التسوية عبر عمولة السائق
        analytic_dist = self._get_analytic_distribution() if self.driver_type == 'internal' else False

        # وصف نوع المصروف بالعربي
        expense_type_labels = {
            'fuel': 'وقود',
            'toll': 'رسوم طريق',
            'maintenance': 'صيانة',
            'other': 'أخرى',
        }
        type_label = expense_type_labels.get(self.expense_type, self.expense_type)

        # اسم الرحلة المرتبطة (لو موجودة)
        trip_ref = ''
        if self.trip_id:
            trip_ref = f' — {self.trip_id.name}'

        # بناء وصف القيد
        line_name = f'{type_label} — سيارة {self.vehicle_id.name or ""}{trip_ref}'
        if self.description:
            line_name = f'{self.description} — {type_label}{trip_ref}'

        # ── إنشاء القيد ──
        move = self.env['account.move'].sudo().create({
            'journal_id': journal.id,
            'date': self.expense_date,
            'ref': f'{self.name} — {type_label} — {self.month_year}',
            'company_id': self.company_id.id,
            'line_ids': [
                # جانب المدين: المصروف + أناليتك السيارة
                (0, 0, {
                    'name': line_name,
                    'account_id': debit_acc.id,
                    'debit': self.amount,
                    'credit': 0.0,
                    'partner_id': self.partner_id.id if self.partner_id else False,
                    'analytic_distribution': analytic_dist,
                }),
                # جانب الدائن: مستحقات / ذمم
                (0, 0, {
                    'name': f'مستحقات مصروف — {self.driver_display or ""} — {self.name}',
                    'account_id': credit_acc.id,
                    'debit': 0.0,
                    'credit': self.amount,
                    'partner_id': self.partner_id.id if self.partner_id else False,
                }),
            ],
        })
        move.sudo().action_post()
        self.move_id = move.id
        self.message_post(
            body=f'قيد المصروف: <b>{move.name}</b> — القيمة: {self.amount:.2f} SAR'
        )

    def action_cancel_to_draft(self):
        """إلغاء تأكيد المصروف وارجاعه لمسودة مع إلغاء القيد المحاسبي."""
        for rec in self:
            if rec.state == 'settled':
                raise ValidationError(
                    'المصروف مُسوَّى في تسوية شهرية ولا يمكن إلغاء التأكيد. ' 'ارجع التسوية أولاً ثم حاول مرة أخرى.'
                )
            if rec.state == 'confirmed':
                # إلغاء القيد المحاسبي لو موجود
                if rec.move_id:
                    try:
                        rec.move_id.sudo().button_cancel()
                        rec.move_id.sudo().with_context(force_delete=True).unlink()
                    except Exception:
                        raise ValidationError(
                            'مفيش إمكانية لإلغاء القيد المحاسبي — تأكد إنه مبيش معروف في مراجعة أو سند دفع.'
                        )
                    rec.move_id = False
                rec.state = 'draft'
                rec.message_post(body='تمت ترجيع المصروف للمسودة.')

    def action_view_move(self):
        self.ensure_one()
        if not self.move_id:
            raise ValidationError('لا يوجد قيد محاسبي مرتبط بهذا المصروف.')
        return {
            'type':      'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id':    self.move_id.id,
            'view_mode': 'form',
            'target':    'current',
        }
