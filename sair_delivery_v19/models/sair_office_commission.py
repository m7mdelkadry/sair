from odoo import models, fields, api
from odoo.exceptions import ValidationError


class SairOfficeCommission(models.Model):
    _name = 'sair.office.commission'
    _description = 'عمولة المكتب - السير المتصل'
    _order = 'commission_date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='رقم العمولة', required=True, copy=False, readonly=True, index='trigram',
        default=lambda self: self.env['ir.sequence'].next_by_code('sair.office.commission') or 'OC/NEW',
    )
    commission_date = fields.Date(string='تاريخ العمولة', required=True, index=True,
                                   default=fields.Date.context_today)
    amount      = fields.Float(string='قيمة العمولة (SAR)', required=True, digits=(10, 2))
    office_id   = fields.Many2one('res.partner', string='المكتب', index=True, ondelete='restrict',
                                   tracking=True, help='المكتب الذي ستخرج العمولات باسمه')
    trip_id     = fields.Many2one('sair.trip', string='الرحلة المصدر', readonly=True,
                                   index=True, ondelete='set null')
    vehicle_id  = fields.Many2one('fleet.vehicle', string='السيارة', index=True, ondelete='restrict')
    driver_display = fields.Char(string='السائق', index='trigram')
    month_year  = fields.Char(string='الشهر/السنة', compute='_compute_month_year', store=True, index=True)
    notes       = fields.Char(string='بيان')
    move_id     = fields.Many2one('account.move', string='قيد الاستحقاق', readonly=True,
                                   copy=False, ondelete='set null')
    payment_id  = fields.Many2one('account.payment', string='سند الدفع', readonly=True,
                                   copy=False, ondelete='set null')
    state = fields.Selection(
        selection=[('draft', 'مسودة'), ('confirmed', 'مستحقة'), ('paid', 'مدفوعة')],
        string='الحالة', default='draft', tracking=True, index=True,
    )
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, index=True)

    @api.depends('commission_date')
    def _compute_month_year(self):
        for rec in self:
            rec.month_year = rec.commission_date.strftime('%Y-%m') if rec.commission_date else ''

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError('قيمة عمولة المكتب لازم تكون أكبر من صفر.')

    def _get_sair_settings(self):
        return self.env['sair.settings'].get_for_company(self.company_id.id)

    def _get_office_commission_journal(self):
        settings = self._get_sair_settings()
        journal = settings.office_commission_journal_id
        if not journal:
            raise ValidationError(
                'لم تُحدد يومية عمولات المكتب في إعدادات السير المتصل. اذهب إلى: السير المتصل ← التهيئة ← الإعدادات'
            )
        return journal

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                continue
            if rec.move_id:
                rec.state = 'confirmed'
                continue

            # ✅ يومية عمولات المكتب بالاسم — مش أي يومية عامة
            journal = rec._get_office_commission_journal()

            settings = rec._get_sair_settings()
            expense_acc = settings.office_commission_expense_account_id
            payable_acc = settings.office_commission_payable_account_id
            if not expense_acc:
                raise ValidationError('لم يُحدد حساب مصروف عمولة المكتب في الإعدادات.')
            if not payable_acc:
                raise ValidationError('لم يُحدد حساب مستحقات المكتب في الإعدادات.')

            # ✅ استخراج الأناليتك من الرحلة لو موجودة (بره الـ create)
            analytic_dist = False
            if rec.trip_id and rec.trip_id.analytic_account_id:
                analytic_dist = {str(rec.trip_id.analytic_account_id.id): 100.0}

            # ✅ إنشاء القيد (الأناليتك جاهزة فوق)
            move = self.env['account.move'].sudo().create({
                'journal_id': journal.id,
                'date': rec.commission_date,
                'ref': f'{rec.name} — عمولة مكتب — {rec.month_year}',
                'company_id': rec.company_id.id,
                'line_ids': [
                    (0, 0, {
                        'name': f'مصروف عمولة مكتب — {rec.notes or rec.name}',
                        'account_id': expense_acc.id,
                        'debit': rec.amount,
                        'credit': 0.0,
                        'partner_id': False,
                        'analytic_distribution': analytic_dist,  # ️هنا خلاص متوفر
                    }),
                    (0, 0, {
                        'name': f'مستحقات عمولة مكتب — {rec.notes or rec.name}',
                        'account_id': payable_acc.id,
                        'debit': 0.0,
                        'credit': rec.amount,
                        'partner_id': rec.office_id.id if rec.office_id else False,
                    }),
                ],
            })
            move.sudo().action_post()
            rec.move_id = move.id
            rec.state = 'confirmed'
            rec.message_post(body=f'قيد الاستحقاق: <b>{move.name}</b>')

    def action_draft(self):
        """ترجيع عمولة المكتب للمسودة وإلغاء القيد المحاسبي."""
        for rec in self:
            if rec.state != 'confirmed':
                continue
            # إلغاء وحذف القيد المحاسبي لو موجود
            if rec.move_id:
                try:
                    rec.move_id.sudo().button_cancel()
                    rec.move_id.sudo().with_context(force_delete=True).unlink()
                except Exception:
                    raise ValidationError(
                        'مفيش capacidade لإلغاء القيد المحاسبي — تأكد إنه مبيش معروف في مراجعة أو سند دفع.'
                    )
                rec.move_id = False
            rec.state = 'draft'
            rec.message_post(body=' تمت ترجيع العمولة للمسودة.')

    def action_register_payment(self):
        self.ensure_one()
        if self.state != 'confirmed':
            raise ValidationError('لازم تأكد العمولة أولاً.')
        if not self.office_id:
            raise ValidationError('حدد المكتب قبل تسجيل الدفع.')

        journal = self.env['account.journal'].search([
            ('type', 'in', ['bank', 'cash']),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not journal:
            raise ValidationError('لا توجد يومية بنك أو صندوق.')

        payment = self.env['account.payment'].sudo().create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id':   self.office_id.id,
            'amount':       self.amount,
            'memo':         f'{self.name} — {self.month_year}',
            'journal_id':   journal.id,
            'company_id':   self.company_id.id,
            'sair_office_commission_id': self.id,
        })
        self.payment_id = payment.id
        return {
            'type': 'ir.actions.act_window', 'res_model': 'account.payment',
            'res_id': payment.id, 'view_mode': 'form', 'target': 'new',
        }

    def action_view_move(self):
        self.ensure_one()
        if not self.move_id:
            raise ValidationError('لا يوجد قيد محاسبي مرتبط.')
        return {
            'type': 'ir.actions.act_window', 'res_model': 'account.move',
            'res_id': self.move_id.id, 'view_mode': 'form', 'target': 'new',
        }

    def action_view_payment(self):
        self.ensure_one()
        if not self.payment_id:
            raise ValidationError('لا يوجد سند دفع مرتبط.')
        return {
            'type': 'ir.actions.act_window', 'res_model': 'account.payment',
            'res_id': self.payment_id.id, 'view_mode': 'form', 'target': 'new',
        }