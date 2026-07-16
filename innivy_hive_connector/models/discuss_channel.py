# -*- coding: utf-8 -*-
import re
import json
import time
import requests
import logging
import threading
from odoo import models
from odoo.api import Environment

_logger = logging.getLogger(__name__)

HIVE_LOG_PREFIX = "INFO_HIVE"
HIVE_BOT_CONTEXT_KEY = 'hive_bot_is_responding'


class DiscussChannel(models.Model):
    _inherit = "discuss.channel"

    def _message_post_after_hook(self, message, msg_vals):
        """
        Hook que se ejecuta justo después de publicar un mensaje en el canal.
        Si un Hive Bot es miembro del canal, intercepta el mensaje y responde.
        """

        if self.env.context.get(HIVE_BOT_CONTEXT_KEY):
            return super()._message_post_after_hook(message, msg_vals)

        author_id = msg_vals.get("author_id", message.author_id.id)
        all_hive_configs = self.env['hive.config'].search([
            ('hive_user_id', '!=', False),
        ])
        all_bot_partner_ids = set(all_hive_configs.mapped('hive_user_id.id'))

        if author_id in all_bot_partner_ids:
            _logger.info("%s | Mensaje de un bot Hive (author_id=%s), ignorando",
                        HIVE_LOG_PREFIX, author_id)
            return super()._message_post_after_hook(message, msg_vals)

        message_type = msg_vals.get("message_type", message.message_type)
        if message_type not in ('comment',):
            return super()._message_post_after_hook(message, msg_vals)

        channel_partner_ids = set(self.channel_member_ids.partner_id.ids)
        hive_configs_in_channel = all_hive_configs.filtered(
            lambda c: c.hive_user_id.id in channel_partner_ids
                    and c.hive_url
                    and c.hive_token
                    and c.is_hive_enabled
        )

        if not hive_configs_in_channel:
            return super()._message_post_after_hook(message, msg_vals)

        user_text = msg_vals.get("body", message.body or "")
        clean_text = re.sub(r'<[^>]+>', "", user_text).strip()

        if not clean_text:
            return super()._message_post_after_hook(message, msg_vals)

        _logger.info("%s | Mensaje del usuario (author_id=%s): '%s'",
                    HIVE_LOG_PREFIX, author_id, clean_text)

        mentioned_partner_ids = set()
        if hasattr(message, 'partner_ids') and message.partner_ids:
            mentioned_partner_ids = set(message.partner_ids.ids)

        for hive_config in hive_configs_in_channel:
            bot_partner = hive_config.hive_user_id

            # En canales grupales (no DM), solo responder si el bot fue mencionado
            if self.channel_type == 'channel' or self.channel_type == 'group':
                if mentioned_partner_ids and bot_partner.id not in mentioned_partner_ids:
                    _logger.info("%s | Bot %s no mencionado en canal grupal, ignorando",
                                HIVE_LOG_PREFIX, bot_partner.name)
                    continue
                if not mentioned_partner_ids:
                    _logger.info("%s | Nadie mencionado en canal grupal, ignorando bot %s",
                                HIVE_LOG_PREFIX, bot_partner.name)
                    continue

            context = []
            if "ventas" in clean_text or "ventas" in clean_text:
                sales = self.env['sale.order'].search([])

                for orden in sales:
                    datos_orden = {
                        'numero': orden.name,
                        'cliente': orden.partner_id.name,
                        'fecha_orden': orden.date_order,
                        'estado': orden.state,
                        'vendedor': orden.user_id.name,
                        'total': orden.amount_total,
                        'subtotal': orden.amount_untaxed,
                        'impuestos': orden.amount_tax,
                        'moneda': orden.currency_id.name,
                        'lineas': []
                    }

                    for linea in orden.order_line:
                        if linea.display_type:
                            continue

                        datos_linea = {
                            'producto': linea.product_id.name,
                            'cantidad': linea.product_uom_qty,
                            'precio_unitario': linea.price_unit,
                            'descuento': linea.discount,
                            'subtotal_linea': linea.price_subtotal,
                            'total_linea': linea.price_total,
                        }
                        datos_orden['lineas'].append(datos_linea)

                    context.append(datos_orden)

                _logger.info("%s | Buscando Ventas: %s",
                            HIVE_LOG_PREFIX, context)

            user_request = f"""
            {clean_text}. Responde en español.
            {json.dumps(context, indent=2, ensure_ascii=False, default=str)}
            """

            _logger.info("%s | Hive configurado (url=%s, bot=%s), enviando a API en thread...",
                        HIVE_LOG_PREFIX, hive_config.hive_url, bot_partner.name)
            thread = threading.Thread(
                target=self._async_query_hive,
                args=(hive_config.hive_url, hive_config.hive_token,
                        user_request, message.id, bot_partner.id),
                daemon=True,
            )
            thread.start()

        return super()._message_post_after_hook(message, msg_vals)


    def _async_query_hive(self, hive_url, hive_token, user_message, message_id, bot_partner_id):
        """
        Ejecuta llamada HTTP a la API de Hive de manera asíncrona.
        Al finalizar, abre un nuevo cursor/entorno en Odoo para escribir la respuesta.
        """

        _logger.info("%s | [THREAD-HIVE] Enviando POST a %s/api/chat ...", HIVE_LOG_PREFIX, hive_url)

        headers = {
            "Authorization": f"Bearer {hive_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "message": user_message,
            "channel": "odoo",
            "thread_id": f"odoo_channel_{self.id}"
        }

        try:
            response = requests.post(
                f"{hive_url}/api/chat",
                headers=headers,
                json=payload,
                timeout=120
            )
            _logger.info("%s | [THREAD-HIVE] Respuesta HTTP: %s", HIVE_LOG_PREFIX, response.status_code)

            if response.status_code == 200:
                res_data = response.json()
                _logger.info("%s | [THREAD-HIVE] Hive response: %s", HIVE_LOG_PREFIX, res_data['content'])
                ai_response = res_data['content']
            else:
                ai_response = (
                    f"Lo siento, no puedo procesar la petición "
                    f"en este momento (HTTP {response.status_code})"
                )
        except Exception as e:
            _logger.warning("%s | [THREAD-HIVE] Error de conexión: %s",
                            HIVE_LOG_PREFIX, e)
            ai_response = f"[ERROR] Error de conexión con Hive: {str(e)}"

        self._post_bot_response(ai_response, bot_partner_id)


    def _post_bot_response(self, ai_response, bot_partner_id):
        """
        Publica la respuesta del bot en el canal usando un cursor nuevo.
        Usa reintentos con backoff para manejar errores de concurrencia de PostgreSQL.
        """
        import random
        max_retries = 5

        for attempt in range(max_retries):
            # Esperar antes de cada intento (más en reintentos)
            if attempt == 0:
                time.sleep(1)
            else:
                wait_time = (2 ** attempt) + random.uniform(0.5, 2.0)
                _logger.info("%s | [THREAD-HIVE] Reintentando en %.1fs...",
                            HIVE_LOG_PREFIX, wait_time)
                time.sleep(wait_time)

            try:
                registry = self.pool
                with registry.cursor() as new_cr:
                    # Context flag HIVE_BOT_CONTEXT_KEY previene que el hook
                    # se vuelva a disparar cuando el bot publica su respuesta
                    new_env = Environment(new_cr, self.env.uid, {
                        HIVE_BOT_CONTEXT_KEY: True,
                        'mail_create_nosubscribe': True,
                    })
                    channel = new_env['discuss.channel'].browse(self.id)

                    channel.sudo().message_post(
                        body=self._format_ai_message(ai_response),
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                        author_id=bot_partner_id,
                        silent=True,
                    )
                _logger.info("%s | [THREAD-HIVE] Respuesta publicada OK (intento %d)",
                            HIVE_LOG_PREFIX, attempt + 1)
                return
            except Exception as e:
                _logger.warning("%s | [THREAD-HIVE] Intento %d falló: %s",
                                HIVE_LOG_PREFIX, attempt + 1, e)
                if attempt >= max_retries - 1:
                    _logger.exception("%s | [THREAD-HIVE] Todos los intentos fallaron",
                                    HIVE_LOG_PREFIX)


    def _format_ai_message(self, text):
        """
        Convierte texto con formato markdown a HTML para Odoo discuss.
        Maneja: headers, listas, negritas, cursivas, código, y saltos de línea.
        """

        if not text:
            return ""

        if not isinstance(text, str):
            text = str(text)

        import html as html_lib

        # Paso 1: Extraer bloques de código para protegerlos
        code_blocks = []
        def _save_code_block(match):
            code_blocks.append(match.group(2).strip())
            return f'\x00CB{len(code_blocks) - 1}\x00'

        text = re.sub(r'```(\w*)\n?(.*?)```', _save_code_block, text, flags=re.DOTALL)

        # Paso 2: Extraer código inline para protegerlo
        inline_codes = []
        def _save_inline_code(match):
            inline_codes.append(match.group(1))
            return f'\x00IC{len(inline_codes) - 1}\x00'

        text = re.sub(r'`([^`]+)`', _save_inline_code, text)

        # Paso 2.5: Extraer y dar formato a matemáticas LaTeX (bloque e inline)
        math_blocks = []
        inline_maths = []

        def _clean_latex(content):
            content = re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'\1 / \2', content)
            content = content.replace('\\approx', '≈')
            content = content.replace('\\times', '×')
            content = content.replace('\\div', '÷')
            content = content.replace('\\pm', '±')
            content = content.replace('\\cdot', '·')
            content = re.sub(r'\\text\{([^}]+)\}', r'\1', content)
            content = re.sub(r'\\mathbf\{([^}]+)\}', r'<b>\1</b>', content)
            content = content.replace('\\,', ' ')
            content = content.replace('\\', '')
            return content.strip()

        def _save_math_block(match):
            content = _clean_latex(match.group(1))
            content = content.replace('\n', '<br/>')
            html_content = f'<div style="background-color: #f0f2f5; padding: 12px; border-radius: 6px; font-family: monospace; margin: 10px 0; color: #333; border-left: 4px solid #714B67;">{content}</div>'
            math_blocks.append(html_content)
            return f'\x00MB{len(math_blocks) - 1}\x00'

        text = re.sub(r'\\\[(.*?)\\\]', _save_math_block, text, flags=re.DOTALL)

        def _save_inline_math(match):
            content = _clean_latex(match.group(1))
            html_content = f'<span style="background-color: #f0f2f5; padding: 2px 6px; border-radius: 4px; font-family: monospace; color: #333;">{content}</span>'
            inline_maths.append(html_content)
            return f'\x00IM{len(inline_maths) - 1}\x00'

        text = re.sub(r'\\\((.*?)\\\)', _save_inline_math, text)

        # Paso 3: Procesar línea por línea
        lines = text.split('\n')
        html_parts = []
        in_ul = False

        for line in lines:
            stripped = line.strip()

            # Líneas vacías
            if not stripped:
                if in_ul:
                    html_parts.append('</ul>')
                    in_ul = False
                html_parts.append('<br/>')
                continue

            # Headers: # ## ### ####
            header_match = re.match(r'^(#{1,6})\s+(.*)', stripped)
            if header_match:
                if in_ul:
                    html_parts.append('</ul>')
                    in_ul = False
                level = len(header_match.group(1))
                content = html_lib.escape(header_match.group(2), quote=False)
                content = self._apply_inline_formatting(content)
                html_parts.append(f'<h{level}>{content}</h{level}>')
                continue

            # Listas con viñeta (incluyendo indentadas): - item o * item
            bullet_match = re.match(r'^\s*[-*]\s+(.*)', stripped)
            if bullet_match:
                if not in_ul:
                    html_parts.append('<ul>')
                    in_ul = True
                content = html_lib.escape(bullet_match.group(1), quote=False)
                content = self._apply_inline_formatting(content)
                html_parts.append(f'<li>{content}</li>')
                continue

            # Items numerados: 1. texto → renderizar como párrafo en negrita
            num_match = re.match(r'^(\d+)\.\s+(.*)', stripped)
            if num_match:
                if in_ul:
                    html_parts.append('</ul>')
                    in_ul = False
                number = num_match.group(1)
                content = html_lib.escape(num_match.group(2), quote=False)
                content = self._apply_inline_formatting(content)
                html_parts.append(f'<b>{number}.</b> {content}<br/>')
                continue

            # Línea de separación: --- o ***
            if re.match(r'^[-*_]{3,}$', stripped):
                if in_ul:
                    html_parts.append('</ul>')
                    in_ul = False
                html_parts.append('<hr/>')
                continue

            # Texto normal
            if in_ul:
                html_parts.append('</ul>')
                in_ul = False
            escaped = html_lib.escape(stripped, quote=False)
            escaped = self._apply_inline_formatting(escaped)
            html_parts.append(f'{escaped}<br/>')

        # Cerrar lista que haya quedado abierta
        if in_ul:
            html_parts.append('</ul>')

        html_text = ''.join(html_parts)

        # Limpiar <br/> consecutivos excesivos (máximo 2)
        html_text = re.sub(r'(<br/>){3,}', '<br/><br/>', html_text)

        # Restaurar bloques de código
        for i, code in enumerate(code_blocks):
            escaped_code = html_lib.escape(code, quote=False)
            html_text = html_text.replace(
                f'\x00CB{i}\x00',
                f'<pre><code>{escaped_code}</code></pre>'
            )

        # Restaurar código inline
        for i, code in enumerate(inline_codes):
            escaped_code = html_lib.escape(code, quote=False)
            html_text = html_text.replace(
                f'\x00IC{i}\x00',
                f'<code>{escaped_code}</code>'
            )

        # Restaurar bloques matemáticos
        for i, html_content in enumerate(math_blocks):
            html_text = html_text.replace(f'\x00MB{i}\x00', html_content)
            
        # Restaurar matemática inline
        for i, html_content in enumerate(inline_maths):
            html_text = html_text.replace(f'\x00IM{i}\x00', html_content)

        from markupsafe import Markup
        return Markup(html_text)

    def _apply_inline_formatting(self, text):
        """Aplica formato inline de markdown: negritas, cursivas."""
        # Negritas: **texto**
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        # Cursivas: *texto* (evita confundir con negritas)
        text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
        return text