from odoo import models, fields, api
from odoo.exceptions import ValidationError


class SairDriverTripsWizard(models.TransientModel):
    _name = 'sair.driver.trips.wizard'
    _description = 'معالج كشف رحلات السائق'

    driver_type = fields.Selection([
        ('all',        'جميع أنواع السائقين'),
        ('internal',   'سائق داخلي - موظف'),
        ('external',   'سائق خارجي - 50/50'),
        ('commission', 'سائق بالعمولة'),
        ('percentage', 'سائق بالنسبة (%)'),
    ], string='نوع السائق', required=True, default='all')

    partner_ids = fields.Many2many(
        'res.partner', 'sair_driver_trips_wizard_partner_rel',
        'wizard_id', 'partner_id',
        string='السائقون (اختر سائق أو أكثر)',
    )

    date_from = fields.Date(
        string='من تاريخ', required=True,
        default=fields.Date.context_today,
    )
    date_to = fields.Date(
        string='إلى تاريخ', required=True,
        default=fields.Date.context_today,
    )

    state = fields.Selection([
        ('all',       'جميع الحالات'),
        ('draft',     'مسودة'),
        ('confirmed', 'مؤكدة'),
        ('settled',   'مُسوَّاة'),
    ], string='حالة الرحلات', required=True, default='all')

    DRIVER_TYPE_AR = {
        'internal':   'سائق داخلي - موظف',
        'external':   'سائق خارجي - 50/50',
        'commission': 'سائق بالعمولة',
        'percentage': 'سائق بالنسبة (%)',
    }

    TRIP_TYPE_AR = {
        'trip_jeddah': 'ترب - جدة',
        'trip_local':  'ترب - محلي',
        'other':       'أخرى',
    }

    STATE_AR = {
        'draft':     'مسودة',
        'confirmed': 'مؤكدة',
        'settled':   'مُسوَّاة',
    }

    @api.onchange('driver_type')
    def _onchange_driver_type(self):
        self.partner_ids = [(5, 0, 0)]

    def _compute_report_data(self):
        self.ensure_one()

        domain = [
            ('trip_date', '>=', str(self.date_from)),
            ('trip_date', '<=', str(self.date_to)),
        ]

        if self.driver_type != 'all':
            domain.append(('driver_type', '=', self.driver_type))

        if self.partner_ids:
            domain.append(('partner_id', 'in', self.partner_ids.ids))

        if self.state != 'all':
            domain.append(('state', '=', self.state))

        trips = self.env['sair.trip'].search(domain, order='driver_type asc, partner_id asc, trip_date asc, id asc')

        # تجميع الرحلات بحسب نوع السائق فقط (جدول واحد لكل نوع)
        grouped_data = {}

        # ترتيب الأنواع بحسب أولويات ثابتة
        type_order = ['external', 'commission', 'percentage', 'internal']

        for t in trips:
            dtype = t.driver_type
            if dtype not in grouped_data:
                grouped_data[dtype] = {
                    'driver_type': dtype,
                    'driver_type_ar': self.DRIVER_TYPE_AR.get(dtype, dtype),
                    'trips': [],
                    'total_amount': 0.0,
                    'total_ext_comm': 0.0,
                    'total_ext_comp_comm': 0.0,
                    'total_driver_share': 0.0,
                    'total_company_share': 0.0,
                    'total_driver_comm': 0.0,
                    'total_company_comm': 0.0,
                    'total_office_comm': 0.0,
                    'total_driver_pct_amount': 0.0,
                    'total_company_pct_amount': 0.0,
                    'total_office_pct_amount': 0.0,
                    'count': 0,
                }

            g = grouped_data[dtype]
            g['count'] += 1
            g['total_amount'] += t.trip_amount

            g['total_ext_comm'] += t.external_commission
            g['total_ext_comp_comm'] += t.external_company_commission
            g['total_driver_share'] += t.driver_share
            g['total_company_share'] += t.company_share

            g['total_driver_comm'] += t.driver_commission
            g['total_company_comm'] += t.company_commission
            g['total_office_comm'] += t.office_commission

            g['total_driver_pct_amount'] += t.driver_percentage_amount
            g['total_company_pct_amount'] += t.company_percentage_amount
            g['total_office_pct_amount'] += t.office_percentage_amount

            g['trips'].append({
                'name': t.name,
                'date': str(t.trip_date),
                'driver': t.driver_display or '',
                'trip_type': self.TRIP_TYPE_AR.get(t.trip_type, t.trip_type),
                'customer': t.customer_id.name if t.customer_id else '',
                'container': t.container_number or '',
                'vehicle': f"{t.vehicle_id.name} ({t.vehicle_id.license_plate})" if t.vehicle_id else '',
                'trip_amount': t.trip_amount,
                'external_commission': t.external_commission,
                'external_company_commission': t.external_company_commission,
                'driver_share': t.driver_share,
                'company_share': t.company_share,
                'driver_commission': t.driver_commission,
                'company_commission': t.company_commission,
                'office_commission': t.office_commission,
                'driver_percentage': t.driver_percentage,
                'driver_percentage_amount': t.driver_percentage_amount,
                'company_percentage_amount': t.company_percentage_amount,
                'office_percentage_amount': t.office_percentage_amount,
                'state': self.STATE_AR.get(t.state, t.state),
                'notes': t.description or '',
            })

        # فرز المجموعات بنفس ترتيب الأنواع
        sorted_groups = []
        for dt in type_order:
            if dt in grouped_data:
                sorted_groups.append(grouped_data[dt])
        for dt, g in grouped_data.items():
            if dt not in type_order:
                sorted_groups.append(g)

        selected_driver_names = []
        if self.partner_ids:
            selected_driver_names.extend(self.partner_ids.mapped('name'))

        selected_driver_disp = ", ".join(selected_driver_names) if selected_driver_names else 'الكل'

        return {
            'date_from': str(self.date_from),
            'date_to': str(self.date_to),
            'driver_type': self.driver_type,
            'driver_type_ar': self.DRIVER_TYPE_AR.get(self.driver_type, 'جميع الأنواع'),
            'selected_driver_name': selected_driver_disp,
            'state_ar': dict(self._fields['state'].selection).get(self.state, 'الكل'),
            'groups': sorted_groups,
            'grand_count': len(trips),
            'grand_amount': sum(t.trip_amount for t in trips),
        }

    def action_print(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise ValidationError('تاريخ البداية يجب أن يكون قبل أو يساوي تاريخ النهاية.')
        return self.env.ref('sair_delivery_v19.action_report_driver_trips').report_action(self)
