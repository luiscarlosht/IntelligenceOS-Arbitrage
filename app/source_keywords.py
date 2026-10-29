"""Pure source keyword formatting; no provider or network imports."""


def search_keywords(product) -> str:
    """Browser fields refine candidate discovery only; they cannot prove identity."""
    context = product.source_context
    if context.get('source_provider') != 'browser-use-walmart':
        return product.name
    parts = [context.get('brand'), product.name, product.variation,
             str(context['piece_count'])+' pieces' if context.get('piece_count') else None,
             context.get('source_package_contents'),
             'pack of '+str(product.package_quantity) if context.get('checkpoint_schema') and product.package_quantity else None]
    query = ' '.join(str(part) for part in parts if part)
    if len(query) > 2048 or any(not c.isprintable() for c in query):
        raise ValueError('Bounded printable candidate query required')
    return query
