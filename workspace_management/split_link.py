def split_link(link: str) -> tuple[str, str]:
    """
    Делит ссылку на путь до объекта ие его название
    :param link: Ссылка или путь
    :return: Кортеж вида ([путь до объекта], [имя объекта])
    """
    last_sep = max(link.rfind('/'), link.rfind('\\'))
    return link[:last_sep], link[last_sep + 1:]
