import base64
import io
from odoo import models, fields, api


class AccountMoveExt(models.Model):
    _inherit = 'account.move'

    sair_trip_id = fields.Many2one('sair.trip', string='رقم الرحلة', compute='_compute_sair_trip', store=True)
    sair_driver_display = fields.Char(string='السائق', compute='_compute_sair_trip', store=True)
    sair_vehicle_display = fields.Char(string='السيارة | رقم اللوحة', compute='_compute_sair_trip', store=True)
    zatca_qr_code = fields.Char(string='QR Code ZATCA (TLV)', compute='_compute_zatca_qr', store=True)
    zatca_qr_image = fields.Binary(string='صورة QR Code', compute='_compute_zatca_qr', store=True, attachment=False)

    @api.depends('name', 'state')
    def _compute_sair_trip(self):
        """يجيب الرحلة عن طريق الـ FK مباشرة (سريع وآمن)"""
        for move in self:
            trip = self.env['sair.trip'].sudo().search([('invoice_id', '=', move.id)], limit=1) if move.id else \
            self.env['sair.trip'].browse()
            if trip:
                move.sair_trip_id = trip.id
                move.sair_driver_display = trip.driver_display or ''
                move.sair_vehicle_display = f"{trip.vehicle_id.name} | {trip.vehicle_id.license_plate}" if trip.vehicle_id else ''
            else:
                move.sair_trip_id = False
                move.sair_driver_display = ''
                move.sair_vehicle_display = ''

    def write(self, vals):
        res = super().write(vals)
        if 'ref' in vals:
            for move in self:
                # نبحث بس لو مفيش رحلة مربوطة أصلاً
                if move.ref and not move.sair_trip_id:
                    trip = self.env['sair.trip'].sudo().search([('name', '=', move.ref), ('invoice_id', '=', False)],
                                                               limit=1)
                    if trip:
                        trip.invoice_id = move.id
        return res

    @api.depends('name', 'invoice_date', 'amount_total', 'amount_tax', 'company_id')
    def _compute_zatca_qr(self):
        """ZATCA Phase 1 QR — TLV base64 + PNG image"""
        for move in self:
            if move.move_type not in ('out_invoice', 'out_refund') or not move.invoice_date:
                move.zatca_qr_code = ''
                move.zatca_qr_image = False
                continue
            try:
                if not move.company_id.vat:
                    move.zatca_qr_code = ''
                    move.zatca_qr_image = False
                    continue

                def tlv(tag, value):
                    v = value.encode('utf-8')
                    return bytes([tag, len(v)]) + v

                tlv_bytes = (
                        tlv(1, move.company_id.name or '') +
                        tlv(2, move.company_id.vat or '') +
                        tlv(3, f"{move.invoice_date}T00:00:00Z") +
                        tlv(4, f"{move.amount_total:.2f}") +
                        tlv(5, f"{move.amount_tax:.2f}")
                )
                qr_data = base64.b64encode(tlv_bytes).decode('ascii')
                move.zatca_qr_code = qr_data

                try:
                    import qrcode
                    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4,
                                       border=2)
                    qr.add_data(qr_data)
                    qr.make(fit=True)
                    img = qr.make_image(fill_color='black', back_color='white')
                    buf = io.BytesIO()
                    img.save(buf, format='PNG')
                    move.zatca_qr_image = base64.b64encode(buf.getvalue())
                except ImportError:
                    move.zatca_qr_image = False

            except Exception:
                move.zatca_qr_code = ''
                move.zatca_qr_image = False

class AccountPaymentSair(models.Model):
    _inherit = 'account.payment'

    sair_settlement_id = fields.Many2one(
        'sair.settlement', string='التسوية المرتبطة',
        ondelete='set null', index=True, copy=False,
    )
    sair_office_commission_id = fields.Many2one(
        'sair.office.commission', string='عمولة المكتب المرتبطة',
        ondelete='set null', index=True, copy=False,
    )

    def action_post(self):
        res = super().action_post()
        for payment in self:
            if (payment.sair_settlement_id
                    and payment.sair_settlement_id.state == 'waiting_payment'):
                payment.sair_settlement_id.state = 'paid'
                payment.sair_settlement_id.message_post(
                    body=(
                        f'تم الدفع عند ترحيل سند الدفع: '
                        f'<b>{payment.name}</b> — '
                        f'المبلغ: {payment.amount:.2f} {payment.currency_id.name}'
                    )
                )
            if (payment.sair_office_commission_id
                    and payment.sair_office_commission_id.state == 'confirmed'):
                payment.sair_office_commission_id.state = 'paid'
                payment.sair_office_commission_id.message_post(
                    body=f'تم الدفع: <b>{payment.name}</b> — {payment.amount:.2f} {payment.currency_id.name}'
                )
        return res
