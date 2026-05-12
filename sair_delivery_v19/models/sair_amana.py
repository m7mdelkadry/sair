from odoo import models, fields, api
from odoo.exceptions import ValidationError


class SairAmana(models.Model):
    _name = 'sair.amana'
    _description = 'عهدة السائق - السير المتصل'
    _order = 'amana_date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='رقم العهدة', required=True, copy=False, readonly=True,
        index='trigram',
        default=lambda self: self.env['ir.sequence'].next_by_code('sair.amana'),
    )
    amana_date  = fields.Date(string='تاريخ العهدة', required=True, index=True, default=fields.Date.context_today)
    driver_type = fields.Selection(
        selection=[
            ('internal',   'سائق داخلي'),
            ('external',   'سائق خارجي 50/50'),
            ('commission', 'سائق بالعمولة'),
        ],
        string='نوع السائق', required=True, index=True,
    )
    employee_id    = fields.Many2one('hr.employee', string='السائق (موظف)',      index=True, ondelete='restrict')
    partner_id     = fields.Many2one('res.partner', string='السائق (خارجي/عمولة)', index=True, ondelete='restrict')
    driver_display = fields.Char(string='السائق', compute='_compute_driver_display', store=True, index='trigram')
    vehicle_id     = fields.Many2one('fleet.vehicle', string='السيارة', index=True, ondelete='restrict')
    amount         = fields.Float(string='المبلغ (SAR)', required=True, digits=(10, 2))
    notes          = fields.Text(string='ملاحظات')

    # ── ربط الرحلة — لما تختار رحلة يجيب بيانات السائق تلقائياً ───────────
    trip_id = fields.Many2one('sair.trip', string='الرحلة المرتبطة', index=True, ondelete='set null')

    settlement_id = fields.Many2one('sair.settlement', string='التسوية', readonly=True, index=True, ondelete='set null')
    state = fields.Selection(
        selection=[('pending', 'معلقة'), ('settled', 'مُسوَّاة')],
        string='الحالة', default='pending', required=True, tracking=True, index=True,
    )
    month_year         = fields.Char(string='الشهر/السنة', compute='_compute_month_year', store=True, index=True)
    company_id         = fields.Many2one('res.company', default=lambda self: self.env.company, index=True)
    analytic_account_id = fields.Many2one('account.analytic.account', string='مركز التكلفة',
                                           compute='_compute_analytic', store=True, readonly=False)

    # ── Compute ──────────────────────────────────────────────────────────────

    @api.depends('employee_id', 'partner_id', 'driver_type', 'trip_id')
    def _compute_driver_display(self):
        for rec in self:
            if rec.trip_id and rec.trip_id.driver_display:
                rec.driver_display = rec.trip_id.driver_display
            if rec.partner_id:
                rec.driver_display = rec.partner_id.name
            else:
                rec.driver_display = ''

    @api.depends('vehicle_id')
    def _compute_analytic(self):
        for rec in self:
            if rec.vehicle_id:
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

    @api.depends('amana_date')
    def _compute_month_year(self):
        for rec in self:
            rec.month_year = rec.amana_date.strftime('%Y-%m') if rec.amana_date else ''

    # ── Onchange — سحب بيانات السائق من الرحلة تلقائياً ─────────────────────

    @api.onchange('trip_id')
    def _onchange_trip_id(self):
        if self.trip_id:
            t = self.trip_id
            self.driver_type = t.driver_type
            self.partner_id = t.partner_id
            self.vehicle_id  = t.vehicle_id
            if not self.amount:
                self.amount = t.trip_amount
            if not self.amana_date:
                self.amana_date = t.trip_date

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError('مبلغ العهدة لازم يكون أكبر من صفر.')
