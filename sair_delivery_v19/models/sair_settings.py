from odoo import models, fields, api
from odoo.exceptions import ValidationError


class SairSettings(models.Model):
    _name = 'sair.settings'
    _description = 'إعدادات السير المتصل'
    _rec_name = 'company_id'

    company_id = fields.Many2one(
        'res.company', string='الشركة', required=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
    )

    # ── مصاريف التشغيل ──────────────────────────────────────────────────────
    operating_expense_journal_id = fields.Many2one(
        'account.journal', string='يومية مصاريف التشغيل',
        domain=[('type', '=', 'general')],
        help='اليومية المستخدمة لتسجيل مصاريف التشغيل اليومية (وقود، صيانة، رسوم طريق...)',
    )
    operating_expense_account_id = fields.Many2one(
        'account.account', string='حساب مصاريف التشغيل',
        domain=[('account_type', '=', 'expense')],
        help='حساب الخصم عند تأكيد مصروف التشغيل',
    )

    # ── عمولة سائق (خارجي / عمولة) ─────────────────────────────────────────
    commission_expense_account_id = fields.Many2one(
        'account.account', string='حساب مصاريف عمولة السائق',
        domain=[('account_type', '=', 'expense')],
        help='حساب المصروف للجانب المدين في تسوية السائق الخارجي / بالعمولة',
    )

    # ── مستحقات السائق الخارجي / العمولة ────────────────────────────────────
    driver_payable_account_id = fields.Many2one(
        'account.account', string='حساب مستحقات سائق (خارجي/عمولة)',
        domain=[('account_type', 'in', ['liability_payable', 'liability_current'])],
        help='حساب الدائن في تسوية السائق الخارجي والسائق بالعمولة',
    )
    settlement_journal_id = fields.Many2one(
        'account.journal', string='يومية تسوية سائق (خارجي/عمولة)',
        domain=[('type', '=', 'general')],
    )

    # ── سائق موظف ───────────────────────────────────────────────────────────
    internal_driver_expense_account_id = fields.Many2one(
        'account.account', string='حساب مصاريف سائق موظف',
        domain=[('account_type', '=', 'expense')],
        help='حساب المصروف في قيد تسوية السائق الموظف (المدين)',
    )
    internal_driver_payable_account_id = fields.Many2one(
        'account.account', string='حساب مستحقات سائق موظف',
        domain=[('account_type', 'in', ['liability_payable', 'liability_current'])],
        help='حساب الدائن في قيد تسوية السائق الموظف — يُدفع منه لاحقاً كمورد',
    )
    internal_settlement_journal_id = fields.Many2one(
        'account.journal', string='يومية تسوية سائق موظف',
        domain=[('type', '=', 'general')],
    )

    # ── عمولات المكتب ────────────────────────────────────────────────────────
    office_commission_journal_id = fields.Many2one(
        'account.journal', string='يومية عمولات المكتب',
        domain=[('type', '=', 'general')],
    )
    office_commission_expense_account_id = fields.Many2one(
        'account.account', string='حساب مصروف عمولة المكتب',
        domain=[('account_type', '=', 'expense')],
    )
    office_commission_payable_account_id = fields.Many2one(
        'account.account', string='حساب مستحقات المكتب',
        domain=[('account_type', 'in', ['liability_payable', 'liability_current'])],
    )

    # ── ذمم دائنة مصاريف (الجانب الدائن عند تأكيد المصروف) ─────────────────
    expense_payable_account_id = fields.Many2one(
        'account.account', string='حساب ذمم دائنة مصاريف',
        domain=[('account_type', 'in', ['liability_payable', 'liability_current'])],
        help='الحساب الدائن عند تأكيد المصروف اليومي — يمثل استحقاق السائق للمصروف',
    )

    _sql_constraints = [
        ('unique_company', 'UNIQUE(company_id)', 'لا يمكن إضافة أكثر من إعداد واحد لنفس الشركة.'),
    ]

    @api.model
    def get_for_company(self, company_id=None):
        """Helper: إرجاع إعدادات الشركة، أو خطأ واضح لو ما أُعِدَّت بعد."""
        cid = company_id or self.env.company.id
        settings = self.search([('company_id', '=', cid)], limit=1)
        if not settings:
            raise ValidationError(
                'لم يتم إعداد السير المتصل لهذه الشركة بعد.\n'
                'اذهب إلى: السير المتصل ← التهيئة ← الإعدادات'
            )
        return settings
