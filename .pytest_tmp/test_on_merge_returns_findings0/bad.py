def bad(x, y, z):
    if x:
        for i in range(x):
            if i % 2:
                while i:
                    if i > 3:
                        for j in range(i):
                            if j:
                                while j:
                                    j -= 1
                    i -= 1
    elif y and z:
        if y > 0:
            pass
        elif z > 0:
            pass
    return x
