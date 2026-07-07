
# -*- coding: utf-8 -*-
from odoo import models, fields

class HiveConfig(models.TransientModel):
    _name = 'hive.config'
    _description = "Hive Configuration"
    
    name = fields.Char(
        required=True
    )
    hive_url = fields.Char(
        string="HIVE API URL", 
        default='http://localhost:18790'
    )
    hive_token = fields.Char(
        string="HIVE AUTH TOKEN",
    )
    is_hive_enabled = fields.Boolean(
        string="ENABLED",
        compute='_compute_is_hive_enabled',
        readonly=False
    )
    
    def _compute_is_hive_enabled(self):
        for record in self:
            if record.hive_url and record.hive_token:
                record.is_hive_enabled = True 
            else:
                record.is_hive_enabled = False 