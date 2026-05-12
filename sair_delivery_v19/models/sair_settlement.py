from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.tools import float_is_zero, float_compare
from datetime import date
import calendar


class SairSettlement(models.Model):
    _name = 'sair.settlement'
    _description = 'تسوية - السير المتصل'
    _order = 'settlement_year desc, settlement_month desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='رقم التسوية', required=True, copy=False, readonly=True,
        index='trigram',
        default=lambda self: self.env['ir.sequence'].next_by_code('sair.settlement'),
    )
    driver_type = fields.Selection(
        selection=[
            ('internal', 'سائق داخلي - موظف'),
            ('external', 'سائق خارجي 50/50'),
            ('commission', 'سائق بالعمولة'),
        ],
        string='نوع السائق', required=True, tracking=True, index=True,
    )
    employee_id = fields.Many2one('hr.employee', string='السائق (موظف)', index=True, ondelete='restrict')
    partner_id = fields.Many2one('res.partner', string='السائق (خارجي/عمولة)', index=True, ondelete='restrict')
    driver_display = fields.Char(string='السائق', compute='_compute_driver_display', store=True, index='trigram')

    settlement_month = fields.Integer(string='الشهر', required=True,
                                      default=lambda self: fields.Date.context_today(self).month)
    settlement_year = fields.Integer(string='السنة', required=True,
                                     default=lambda self: fields.Date.context_today(self).year)
    month_year = fields.Char(string='الفترة', compute='_compute_month_year_label', store=True)

    # ── One2many ─────────────────────────────────────────────────────────────
    trip_ids = fields.One2many('sair.trip', 'settlement_id', string='الرحلات', readonly=True)
    amana_ids = fields.One2many('sair.amana', 'settlement_id', string='العهدات', readonly=True)
    expense_ids = fields.One2many('sair.driver.expense', 'settlement_id', string='المصاريف', readonly=True)

    # ── إجماليات ─────────────────────────────────────────────────────────────
    total_revenue = fields.Float(string='إجمالي الإيراد', compute='_compute_totals', store=True, digits=(10, 2))
    total_expenses = fields.Float(string='إجمالي المصاريف', compute='_compute_totals', store=True, digits=(10, 2))
    total_amana = fields.Float(string='عهد مستلمة من العميل', compute='_compute_totals', store=True, digits=(10, 2))

    # ── عمولة المكتب ──────────────────────────────────────────────────────────
    office_commission = fields.Float(
        string='عمولة المكتب', compute='_compute_office_commission',
        store=True, digits=(10, 2), tracking=True,
        help='الفرق بين إجمالي الإيراد وحصتي السائق والشركة',
    )


    # ── حصص ─────────────────────────────────────────────────────────────────
    driver_revenue_share = fields.Float(string='إيراد/عمولة السائق', compute='_compute_net', store=True, digits=(10, 2))
    company_revenue_share = fields.Float(string='إيراد/عمولة الشركة', compute='_compute_net', store=True,
                                         digits=(10, 2))
    driver_expense_share = fields.Float(string='مصاريف السائق', compute='_compute_net', store=True, digits=(10, 2))
    company_expense_share = fields.Float(string='مصاريف الشركة', compute='_compute_net', store=True, digits=(10, 2))
    net_to_driver = fields.Float(string='مستحقات السائق', compute='_compute_net', store=True, digits=(10, 2))
    net_to_company = fields.Float(string='صافي الشركة', compute='_compute_net', store=True, digits=(10, 2))

    # ── محاسبة ───────────────────────────────────────────────────────────────
    invoice_id = fields.Many2one(
        'account.move', string='قيد الاستحقاق', readonly=True, copy=False, ondelete='set null',
    )
    payment_id = fields.Many2one(
        'account.payment', string='سند الدفع', readonly=True, copy=False, ondelete='set null',
    )

    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('waiting_payment', 'في انتظار الدفع'),
            ('confirmed', 'مؤكدة'),
            ('paid', 'مدفوعة'),
        ],
        string='الحالة', default='draft', required=True, tracking=True, index=True,
    )
    confirmed_by = fields.Many2one('res.users', string='أُقرَّت بواسطة', readonly=True, copy=False)
    confirmed_date = fields.Datetime(string='تاريخ الإقرار', readonly=True, copy=False)
    notes = fields.Text(string='ملاحظات')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, index=True)

    # ═══════════════════════════════════════════════════════════════════════
    #  Computes
    # ═══════════════════════════════════════════════════════════════════════

    @api.depends('partner_id', 'driver_type')
    def _compute_driver_display(self):
        for rec in self:
            rec.driver_display = rec.partner_id.name if rec.partner_id else ''

    @api.depends('settlement_month', 'settlement_year')
    def _compute_month_year_label(self):
        months_ar = {
            1: 'يناير', 2: 'فبراير', 3: 'مارس', 4: 'أبريل',
            5: 'مايو', 6: 'يونيو', 7: 'يوليو', 8: 'أغسطس',
            9: 'سبتمبر', 10: 'أكتوبر', 11: 'نوفمبر', 12: 'ديسمبر',
        }
        for rec in self:
            if rec.settlement_month and rec.settlement_year:
                m = months_ar.get(rec.settlement_month, str(rec.settlement_month))
                rec.month_year = f"{m} {rec.settlement_year}"
            else:
                rec.month_year = ''

    @api.depends('trip_ids.trip_amount', 'expense_ids.amount', 'amana_ids.amount')
    def _compute_totals(self):
        for rec in self:
            rec.total_revenue = sum(rec.trip_ids.mapped('trip_amount'))
            rec.total_expenses = sum(rec.expense_ids.mapped('amount'))
            rec.total_amana = sum(rec.amana_ids.mapped('amount'))

    @api.depends('total_revenue', 'driver_revenue_share', 'company_revenue_share')
    def _compute_office_commission(self):
        for rec in self:
            val = rec.total_revenue - rec.driver_revenue_share - rec.company_revenue_share
            rec.office_commission = max(0.0, val)

    # ═══════════════════════════════════════════════════════════════════════
    #  المنطق الموحد
    #
    #  net_to_driver  = rev_drv + cmp_exp   (حصة السائق + مصاريف الشركة عليه)
    #  net_to_company = company_revenue_share - cmp_exp (عمولة الشركة - مصاريفها)
    #
    #  القيد المحاسبي دائماً:
    #    DEBIT  مصروف عمولات        = drv_rev   (حصة/عمولة السائق بالكامل)
    #    DEBIT  مصاريف تشغيل         = cmp_exp   (حصة الشركة من المصاريف فقط)
    #    CREDIT مستحقات السائق       = drv_rev + cmp_exp
    # ═══════════════════════════════════════════════════════════════════════

    @api.depends(
        'trip_ids.driver_commission', 'trip_ids.company_commission',
        'trip_ids.driver_share', 'trip_ids.company_share',
        'expense_ids.driver_expense_share', 'expense_ids.company_expense_share',
        'total_revenue', 'total_expenses', 'driver_type',
    )
    def _compute_net(self):
        for rec in self:
            drv_exp = sum(rec.expense_ids.mapped('driver_expense_share'))
            cmp_exp = sum(rec.expense_ids.mapped('company_expense_share'))

            if rec.driver_type == 'external':
                rev_drv = rec.total_revenue * 0.50
                rec.driver_revenue_share = rev_drv
                rec.company_revenue_share = rec.total_revenue * 0.50
                rec.driver_expense_share = drv_exp
                rec.company_expense_share = cmp_exp
                # net_to_driver = حصة السائق (1000) + مصاريف الشركة (200) = 1200
                rec.net_to_driver = rev_drv + cmp_exp
                # صافي الشركة = حصتها من الإيراد - مصاريفها
                rec.net_to_company = rec.company_revenue_share - cmp_exp

            elif rec.driver_type == 'commission':
                drv_comm = sum(rec.trip_ids.mapped('driver_commission'))
                cmp_comm = sum(rec.trip_ids.mapped('company_commission'))
                rec.driver_revenue_share = drv_comm
                rec.company_revenue_share = cmp_comm
                rec.driver_expense_share = drv_exp
                rec.company_expense_share = cmp_exp
                # net_to_driver = عمولة السائق + مصاريف الشركة = مستحقاته الكاملة
                rec.net_to_driver = drv_comm + cmp_exp
                # صافي الشركة = عمولة الشركة - مصاريف الشركة
                rec.net_to_company = cmp_comm - cmp_exp

            else:  # internal
                rec.driver_revenue_share = 0.0
                rec.company_revenue_share = rec.total_revenue
                rec.driver_expense_share = 0.0
                rec.company_expense_share = rec.total_expenses
                # السائق الموظف يستحق مصاريف التشغيل التي دفعها نيابةً عن الشركة
                rec.net_to_driver = rec.total_expenses
                rec.net_to_company = rec.total_revenue - rec.total_expenses

    # ═══════════════════════════════════════════════════════════════════════
    #  Actions
    # ═══════════════════════════════════════════════════════════════════════

    def action_load_data(self):
        for rec in self:
            if rec.state != 'draft':
                raise ValidationError('التسوية لازم تكون في حالة مسودة.')

            d_domain = [
                ('partner_id', '=', rec.partner_id.id),
                ('driver_type', '=', rec.driver_type),
            ]

            month_str = f"{rec.settlement_year}-{rec.settlement_month:02d}"
            base_trip = d_domain + [
                ('month_year', '=', month_str),
                ('settlement_id', '=', False),
                ('state', '=', 'confirmed'),
            ]
            base_rest = d_domain + [
                ('month_year', '=', month_str),
                ('settlement_id', '=', False),
            ]

            trips = self.env['sair.trip'].search(base_trip)
            amanas = self.env['sair.amana'].search(base_rest + [('state', '=', 'pending')])
            expenses = self.env['sair.driver.expense'].search(base_rest + [('state', '=', 'confirmed')])

            trips.write({'settlement_id': rec.id})
            amanas.write({'settlement_id': rec.id})
            expenses.write({'settlement_id': rec.id})

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise ValidationError('التسوية مش في حالة مسودة.')
            if not rec.trip_ids:
                raise ValidationError('مفيش رحلات. اضغط "تحميل بيانات الفترة" أولاً.')

            rec.amana_ids.write({'state': 'settled'})
            rec.trip_ids.write({'state': 'settled'})
            rec.expense_ids.write({'state': 'settled'})
            rec.confirmed_by = self.env.user.id
            rec.confirmed_date = fields.Datetime.now()

            if rec.driver_type == 'internal':
                from odoo.tools import float_is_zero
                prec = self.env['decimal.precision'].precision_get('Account')
                if float_is_zero(rec.net_to_driver, precision_digits=prec):
                    rec.state = 'paid'
                    rec.message_post(body='تسوية السائق الموظف مؤكدة — لا توجد مصاريف تشغيل مستحقة.')
                else:
                    if not rec.partner_id:
                        raise ValidationError(
                            f'لازم يكون في شريك (سائق) مرتبط بالتسوية.'
                        )
                    rec._create_account_move()
                    rec.state = 'waiting_payment'
                    rec.message_post(
                        body=(
                            f'قيد الاستحقاق صدر — مستحقات مصاريف التشغيل: '
                            f'{rec.net_to_driver:.2f} SAR\n'
                            'اضغط "تسجيل دفع للشريك" لسداد مستحقات المصاريف.'
                        )
                    )
            else:
                rec._create_account_move()
                rec.state = 'waiting_payment'
                rec.message_post(
                    body=(
                        f'قيد الاستحقاق صدر — إجمالي صافي مستحق السائق: '
                        f'{rec.net_to_driver:.2f} SAR\n'
                        f'اضغط "تسجيل دفع" لسداد المستحقات.'
                    )
                )

    # ═══════════════════════════════════════════════════════════════════════
    #  قيد الاستحقاق — النسخة الموحدة (لا يختلف حسب طريقة الدفع)
    #
    #  القيد دائماً:
    #    DEBIT  مصروف عمولات        drv_rev   (حصة/عمولة السائق)
    #    DEBIT  مصاريف تشغيل         cmp_exp   (حصة الشركة من المصاريف)
    #    CREDIT مستحقات السائق       drv_rev + cmp_exp
    #
    #  المقاصة الفعلية (المعادلة):
    #    السائق يدين الشركة بالعهدة = total_amana
    #    الشركة تدين السائق (مستحقات) = net_to_driver
    #    صافي ما يدفعه السائق = total_amana - net_to_driver
    # ═══════════════════════════════════════════════════════════════════════

    def _build_trip_ref_string(self):
        """بناء نص مرجعي من أرقام الرحلات لتضمينه في تسميات القيد."""
        refs = self.trip_ids.mapped('name')
        if not refs:
            return ''
        ref_str = ', '.join(refs[:5])
        if len(refs) > 5:
            ref_str += f'... و{len(refs) - 5} أخرى'
        return ref_str

    def _get_sair_settings(self):
        return self.env['sair.settings'].get_for_company(self.company_id.id)

    def _get_settlement_journal(self, driver_type=None):
        settings = self._get_sair_settings()
        dt = driver_type or self.driver_type
        if dt == 'internal':
            journal = settings.internal_settlement_journal_id
            label = 'يومية تسوية سائق موظف'
        else:
            journal = settings.settlement_journal_id
            label = 'يومية تسوية سائق (خارجي/عمولة)'
        if not journal:
            raise ValidationError(
                f'لم تُحدد [{label}] في إعدادات السير المتصل. اذهب إلى: السير المتصل ← التهيئة ← الإعدادات'
            )
        return journal

    def _get_commission_expense_account(self):
        settings = self._get_sair_settings()
        acc = settings.commission_expense_account_id
        if not acc:
            raise ValidationError(
                'لم يُحدد حساب مصاريف عمولة السائق في الإعدادات. اذهب إلى: السير المتصل ← التهيئة ← الإعدادات'
            )
        return acc

    def _get_operating_expense_account(self):
        settings = self._get_sair_settings()
        acc = settings.operating_expense_account_id
        if not acc:
            raise ValidationError(
                'لم يُحدد حساب مصاريف التشغيل في الإعدادات. اذهب إلى: السير المتصل ← التهيئة ← الإعدادات'
            )
        return acc

    def _get_driver_payable_account(self):
        settings = self._get_sair_settings()
        if self.driver_type == 'internal':
            acc = settings.internal_driver_payable_account_id
            label = 'حساب مستحقات سائق موظف'
        else:
            acc = settings.driver_payable_account_id
            label = 'حساب مستحقات سائق (خارجي/عمولة)'
        if not acc:
            raise ValidationError(
                f'لم يُحدد [{label}] في الإعدادات. اذهب إلى: السير المتصل ← التهيئة ← الإعدادات'
            )
        return acc

    def _create_account_move(self):
        prec = self.env['decimal.precision'].precision_get('Account')

        for rec in self:
            last_day = calendar.monthrange(rec.settlement_year, rec.settlement_month)[1]
            move_date = date(rec.settlement_year, rec.settlement_month, last_day)
            journal = rec._get_settlement_journal()
            payable_acc = rec._get_driver_payable_account()
            trip_ref = rec._build_trip_ref_string()

            analytic_dist = False
            if rec.trip_ids and rec.trip_ids[0].analytic_account_id:
                analytic_dist = {str(rec.trip_ids[0].analytic_account_id.id): 100.0}

            if rec.driver_type == 'internal':
                cmp_exp = rec.company_expense_share
                if float_is_zero(cmp_exp, precision_digits=prec):
                    continue

                partner = rec.partner_id
                if not partner:
                    raise ValidationError(
                        f'لازم يكون في شريك مرتبط بالتسوية {rec.name}.'
                    )

                operating_acc = rec._get_operating_expense_account()
                lines = [
                    (0, 0, {
                        'name': f'مصاريف تشغيل (سائق موظف) — {rec.driver_display} — {rec.month_year}'
                                + (f' — {trip_ref}' if trip_ref else ''),
                        'account_id': operating_acc.id,
                        'debit': cmp_exp, 'credit': 0.0,
                        'partner_id': False,
                        'analytic_distribution': False,  # لا تخصم الأناليتك مرة ثانية — المصروف خصمها عند تأكيده
                    }),
                    (0, 0, {
                        'name': f'مستحقات مصاريف السائق — {rec.driver_display} — {rec.name}',
                        'account_id': payable_acc.id,
                        'debit': 0.0, 'credit': cmp_exp,
                        'partner_id': partner.id,
                    }),
                ]

            else:
                drv_rev = rec.driver_revenue_share
                cmp_exp = rec.company_expense_share
                net_to_pay = drv_rev + cmp_exp

                if float_is_zero(drv_rev, precision_digits=prec) and float_is_zero(cmp_exp, precision_digits=prec):
                    continue

                partner_id = rec.partner_id.id if rec.partner_id else False
                if not partner_id:
                    raise ValidationError(f'لازم يكون في شريك (سائق) مرتبط بالتسوية {rec.name}.')

                commission_acc = rec._get_commission_expense_account()
                operating_acc = rec._get_operating_expense_account()
                lines = []

                if not float_is_zero(drv_rev, precision_digits=prec):
                    lines.append((0, 0, {
                        'name': f'مصروف عمولات سائق — {rec.driver_display} — {rec.month_year}'
                                + (f' — {trip_ref}' if trip_ref else ''),
                        'account_id': commission_acc.id,
                        'debit': drv_rev, 'credit': 0.0,
                        'partner_id': False,
                        'analytic_distribution': analytic_dist,
                    }))

                if not float_is_zero(cmp_exp, precision_digits=prec):
                    lines.append((0, 0, {
                        'name': f'مصاريف تشغيل (حصة شركة) — {rec.month_year}',
                        'account_id': operating_acc.id,
                        'debit': cmp_exp, 'credit': 0.0,
                        'partner_id': False,
                        'analytic_distribution': False,  # المصاريف مدمجة في عمولة السائق — لا تخصم الأناليتك مرة ثانية
                    }))

                if not float_is_zero(net_to_pay, precision_digits=prec):
                    lines.append((0, 0, {
                        'name': f'مستحقات السائق — {rec.driver_display} — {rec.name}',
                        'account_id': payable_acc.id,
                        'debit': 0.0, 'credit': net_to_pay,
                        'partner_id': partner_id,
                    }))

            if not lines:
                continue

            move = self.env['account.move'].sudo().create({
                'journal_id': journal.id,
                'date': move_date,
                'ref': f'مستحقات — {rec.name} — {rec.month_year}',
                'company_id': rec.company_id.id,
                'line_ids': lines,
            })
            move.sudo().action_post()
            rec.invoice_id = move.id

    # ═══════════════════════════════════════════════════════════════════════
    #  الدفع
    # ═══════════════════════════════════════════════════════════════════════

    def action_register_payment(self):
        self.ensure_one()
        if self.state != 'waiting_payment':
            raise ValidationError('التسوية لازم تكون في حالة "في انتظار الدفع".')
        if self.net_to_driver <= 0:
            raise ValidationError('صافي المستحق للسائق صفر أو سالب — لا يوجد مستحق للدفع.')

        partner = self.partner_id
        if not partner:
            raise ValidationError('لازم يكون في شريك (سائق) مرتبط بالتسوية.')

        journal = self.env['account.journal'].search([
            ('type', 'in', ['bank', 'cash']),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

        payment = self.env['account.payment'].sudo().create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': partner.id,
            'amount': self.net_to_driver,
            'memo': f'{self.name} — {self.driver_display} — {self.month_year}',
            'sair_settlement_id': self.id,
            'journal_id': journal.id if journal else False,
        })
        self.payment_id = payment.id

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'res_id': payment.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_payment(self):
        self.ensure_one()
        if not self.payment_id:
            raise ValidationError('لا يوجد سند دفع مرتبط.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'res_id': self.payment_id.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_move(self):
        self.ensure_one()
        if not self.invoice_id:
            raise ValidationError('لا يوجد قيد محاسبي مرتبط.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_mark_paid(self):
        for rec in self:
            if rec.state not in ('waiting_payment', 'confirmed'):
                raise ValidationError('الحالة الحالية لا تسمح بتسجيل الدفع.')
            rec.state = 'paid'

    def action_print_settlement(self):
        return self.env.ref('sair_delivery_v19.action_report_settlement').report_action(self)

    # ═══════════════════════════════════════════════════════════════════════
    #  Constraints
    # ═══════════════════════════════════════════════════════════════════════

    @api.constrains('settlement_month', 'settlement_year', 'driver_type', 'partner_id')
    def _check_unique_settlement(self):
        for rec in self:
            domain = [
                ('driver_type', '=', rec.driver_type),
                ('settlement_month', '=', rec.settlement_month),
                ('settlement_year', '=', rec.settlement_year),
                ('id', '!=', rec.id),
                ('partner_id', '=', rec.partner_id.id),
            ]

            if self.search_count(domain) > 0:
                raise ValidationError(
                    f'في تسوية موجودة للسائق {rec.driver_display} في نفس الفترة.'
                )
