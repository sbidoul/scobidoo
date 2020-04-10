def init_sc_state(cr, registry):
    """Initialize sc_state for existing account.move records."""
    init_map = [
        ("draft", "draft"),
        ("posted", "posted"),
        ("cancel", "cancelled"),
    ]
    for (odoo_state, sc_state) in init_map:
        cr.execute(
            f"""\
                UPDATE account_move
                SET sc_state = '{{"configuration": ["root", "{sc_state}"]}}'
                WHERE sc_state IS NULL AND state='{odoo_state}'
            """
        )
