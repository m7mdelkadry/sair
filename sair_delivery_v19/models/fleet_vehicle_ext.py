from odoo import models, fields, api
from odoo.exceptions import ValidationError


class FleetVehicleExt(models.Model):
    _inherit = 'fleet.vehicle'

    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='مركز تكلفة السيارة',
        index=True, ondelete='restrict',
        help='حساب أناليتك يُنشأ يدوياً من المحاسبة ثم يُربط هنا',
    )

    trip_count = fields.Integer(string='عدد الرحلات', compute='_compute_vehicle_stats')
    total_trips_revenue = fields.Float(string='إيراد الرحلات', compute='_compute_vehicle_stats')

    def _compute_vehicle_stats(self):
        for rec in self:
            trips = self.env['sair.trip'].search([('vehicle_id', '=', rec.id)])
            rec.trip_count = len(trips)
            rec.total_trips_revenue = sum(trips.mapped('trip_amount'))

    def action_view_vehicle_trips(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'رحلات {self.name}',
            'res_model': 'sair.trip',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
        }

    def action_view_analytic_account(self):
        self.ensure_one()
        if not self.analytic_account_id:
            raise ValidationError(
                'لا يوجد مركز تكلفة مرتبط بهذه السيارة.\n'
                'أنشئ حساب أناليتك من: محاسبة ← تحليل المصاريف، ثم ارجع وارتبطه هنا.'
            )
        return {
            'type': 'ir.actions.act_window',
            'name': f'مركز تكلفة {self.name}',
            'res_model': 'account.analytic.account',
            'res_id': self.analytic_account_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
