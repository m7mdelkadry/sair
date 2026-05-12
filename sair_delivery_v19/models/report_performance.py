from odoo import models, api


MONTHS_AR = {
    '01': 'يناير', '02': 'فبراير', '03': 'مارس',    '04': 'أبريل',
    '05': 'مايو',  '06': 'يونيو',  '07': 'يوليو',   '08': 'أغسطس',
    '09': 'سبتمبر','10': 'أكتوبر','11': 'نوفمبر',  '12': 'ديسمبر',
}

EXPENSE_TYPE_AR = {
    'fuel':        'وقود',
    'toll':        'رسوم طريق',
    'maintenance': 'صيانة',
    'other':       'أخرى',
}


class SairReportPerformance(models.AbstractModel):
    """
    Parser لتقرير أداء السيارة.
    الاسم يجب أن يطابق: report.<module>.<template_id>
    """
    _name = 'report.sair_delivery_v19.report_performance_template'
    _description = 'Parser تقرير أداء السيارة والسائق'

    @api.model
    def _get_report_values(self, docids, data=None):
        wizard = self.env['sair.performance.wizard'].browse(docids)

        month_year_key   = f"{wizard.year}-{wizard.month}"
        month_year_label = f"{MONTHS_AR.get(wizard.month, wizard.month)} {wizard.year}"

        # ── بناء الـ domain ──────────────────────────────────────────────────
        base_domain = [('month_year', '=', month_year_key)]
        if wizard.vehicle_id:
            base_domain.append(('vehicle_id', '=', wizard.vehicle_id.id))

        trips    = self.env['sair.trip'].search(
            base_domain, order='vehicle_id, trip_date, id')
        expenses = self.env['sair.driver.expense'].search(
            base_domain, order='vehicle_id, expense_date, id')

        # ── تجميع البيانات per سيارة (dict keyed by vehicle.id) ─────────────
        vehicles = {}

        for trip in trips:
            vid = trip.vehicle_id.id or 0
            if vid not in vehicles:
                vehicles[vid] = _empty_vehicle_bucket(trip.vehicle_id)
            vehicles[vid]['trips'].append(trip)
            vehicles[vid]['total_revenue'] += trip.trip_amount

        for exp in expenses:
            vid = exp.vehicle_id.id or 0
            if vid not in vehicles:
                vehicles[vid] = _empty_vehicle_bucket(exp.vehicle_id)
            vehicles[vid]['expenses'].append(exp)
            vehicles[vid]['total_expense'] += exp.amount

        # ── حساب صافي كل سيارة وترتيب حسب اسمها ────────────────────────────
        vehicle_list = sorted(
            vehicles.values(),
            key=lambda v: (v['vehicle'].name or '') if v['vehicle'] else '',
        )
        for v in vehicle_list:
            v['net'] = v['total_revenue'] - v['total_expense']

        grand_revenue = sum(v['total_revenue'] for v in vehicle_list)
        grand_expense = sum(v['total_expense'] for v in vehicle_list)

        return {
            'doc_ids':           docids,
            'doc_model':         'sair.performance.wizard',
            'docs':              wizard,
            'vehicles':          vehicle_list,
            'month_year_label':  month_year_label,
            'vehicle_filter':    wizard.vehicle_id.name if wizard.vehicle_id else 'جميع السيارات',
            'grand_revenue':     grand_revenue,
            'grand_expense':     grand_expense,
            'grand_net':         grand_revenue - grand_expense,
            'expense_type_ar':   EXPENSE_TYPE_AR,
        }


def _empty_vehicle_bucket(vehicle):
    return {
        'vehicle':       vehicle,
        'trips':         [],
        'expenses':      [],
        'total_revenue': 0.0,
        'total_expense': 0.0,
        'net':           0.0,
    }
