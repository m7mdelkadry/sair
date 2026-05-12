from odoo import models, fields, api
from odoo.exceptions import ValidationError


MONTHS_AR = {
    '01': 'يناير', '02': 'فبراير', '03': 'مارس',    '04': 'أبريل',
    '05': 'مايو',  '06': 'يونيو',  '07': 'يوليو',   '08': 'أغسطس',
    '09': 'سبتمبر','10': 'أكتوبر','11': 'نوفمبر',  '12': 'ديسمبر',
}


class SairPerformanceWizard(models.TransientModel):
    _name = 'sair.performance.wizard'
    _description = 'ويزرد تقرير أداء السيارة والسائق'

    month = fields.Selection(
        selection=[
            ('01', 'يناير'),  ('02', 'فبراير'), ('03', 'مارس'),
            ('04', 'أبريل'), ('05', 'مايو'),   ('06', 'يونيو'),
            ('07', 'يوليو'), ('08', 'أغسطس'),  ('09', 'سبتمبر'),
            ('10', 'أكتوبر'),('11', 'نوفمبر'), ('12', 'ديسمبر'),
        ],
        string='الشهر', required=True,
        default=lambda self: fields.Date.context_today(self).strftime('%m'),
    )
    year = fields.Selection(
        selection=[(str(y), str(y)) for y in range(2024, 2031)],
        string='السنة', required=True,
        default=lambda self: str(fields.Date.context_today(self).year),
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='السيارة',
        help='اتركه فارغاً لعرض جميع السيارات',
    )

    def action_print_report(self):
        self.ensure_one()
        # ── التحقق من وجود بيانات قبل طباعة التقرير ─────────────────────────
        month_year_key = f"{self.year}-{self.month}"
        domain = [('month_year', '=', month_year_key)]
        if self.vehicle_id:
            domain.append(('vehicle_id', '=', self.vehicle_id.id))

        has_trips    = bool(self.env['sair.trip'].search(domain, limit=1))
        has_expenses = bool(self.env['sair.driver.expense'].search(domain, limit=1))
        if not has_trips and not has_expenses:
            raise ValidationError(
                f'لا توجد رحلات أو مصاريف في الفترة: '
                f'{MONTHS_AR.get(self.month)} {self.year}'
            )

        return self.env.ref(
            'sair_delivery_v19.action_report_performance'
        ).report_action(self)
