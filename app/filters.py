def register_filters(app):
    @app.template_filter("pct")
    def pct(v, nd=1):
        return "–" if v is None else f"{v * 100:.{nd}f}%"

    @app.template_filter("num")
    def num(v):
        return "–" if v is None else f"{v:,.0f}"

    @app.template_filter("dec")
    def dec(v, nd=2):
        return "–" if v is None else f"{v:,.{nd}f}"

    @app.template_filter("signed")
    def signed(v, nd=1):
        return "–" if v is None else f"{v:+.{nd}f}"

    @app.template_filter("stars")
    def stars(v):
        if v is None:
            return "–"
        full = int(round(v))
        return "★" * full + "☆" * (5 - full) + f"  {v:.1f}"
