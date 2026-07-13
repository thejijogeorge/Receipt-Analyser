import re


def split_on_dashes(lines, min_length=5):
    """Split a list of stripped lines into blocks, using lines that are
    entirely dashes (any length >= min_length) as delimiters. Used for
    receipts (JB Hi-Fi, Woolworths) that separate transaction/gift-card
    blocks with dashed lines rather than a repeated header like Coles does.

    min_length matters because some receipts (Woolworths) use a short
    dashed line as a purely visual sub-divider *inside* one logical block
    (e.g. between a redemption request and its approval response), not as
    a boundary between separate transactions. Callers with that quirk
    should pass a higher min_length so short inner dividers aren't
    mistaken for block boundaries.
    """
    dash_line_re = re.compile(r'^-{%d,}$' % min_length)
    blocks = []
    current = []
    for line in lines:
        if dash_line_re.match(line):
            if current:
                blocks.append(current)
            current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks
