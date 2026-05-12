from odoo import models, fields, api
from odoo.exceptions import ValidationError


class CustomerStatementWizard(models.TransientModel):
    _name = 'sair.customer.statement.wizard'
    _description = 'معالج كشف العميل'

    customer_id = fields.Many2one(
        'res.partner', string='العميل',
        required=True, domain=[('customer_rank', '>', 0)],
    )
    date_from = fields.Date(string='من تاريخ', required=True, default=fields.Date.context_today)
    date_to   = fields.Date(string='الى تاريخ', required=True, default=fields.Date.context_today)
    report_type = fields.Selection([
        ('company', 'كشف للشركة (تفصيلي)'),
        ('customer', 'كشف للعميل (مبسط)'),
    ], string='نوع الكشف', required=True, default='company')

    TRIP_TYPE_AR = {
        'trip_jeddah': 'ترب - جدة',
        'trip_local':  'ترب - محلي',
        'other':       'أخرى',
    }

    def _compute_statement_lines(self):
        """
        يبني بيانات الكشف — يُستدعى من AbstractModel في _get_report_values.
        يُرجع dict جاهز للـ template.
        """
        self.ensure_one()
        trips = self.env['sair.trip'].search([
            ('customer_id', '=', self.customer_id.id),
            ('trip_date',   '>=', str(self.date_from)),
            ('trip_date',   '<=', str(self.date_to)),
            ('state', 'not in', ['draft']),
        ], order='trip_date asc')

        lines   = []
        balance = 0.0

        for t in trips:
            balance += t.trip_amount
            if t.driver_type == 'commission':
                comm_co  = t.company_commission
                comm_off = t.office_commission
            elif t.driver_type == 'external':
                comm_co  = t.company_share
                comm_off = 0.0
            else:
                comm_co  = t.company_share
                comm_off = 0.0

            lines.append({
                'date':       str(t.trip_date),
                'trip_name':  t.name,
                'trip_type':  self.TRIP_TYPE_AR.get(t.trip_type, ''),
                'driver':     t.driver_display or '',
                'vehicle':    t.vehicle_id.license_plate if t.vehicle_id else '',
                'debit':      t.trip_amount,
                'comm_co':    comm_co,
                'comm_off':   comm_off,
                'balance':    balance,
                'notes':      t.description or '',
                'cash':       'نعم' if t.cash_collected else '',
                'invoice_no': t.invoice_id.name if t.invoice_id else '',
                'state':      t.state,
            })

        return {
            'customer_name': self.customer_id.name,
            'date_from':     str(self.date_from),
            'date_to':       str(self.date_to),
            'lines':         lines,
            'total_debit':   sum(l['debit'] for l in lines),
            'total_balance': balance,
            'trip_count':    len(lines),
            'report_type':   self.report_type,  # ✅ إضافة النوع
        }

    def action_print(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise ValidationError('تاريخ البداية لازم يكون قبل تاريخ النهاية.')
        return self.env.ref(
            'sair_delivery_v19.action_report_customer_statement'
        ).report_action(self)
