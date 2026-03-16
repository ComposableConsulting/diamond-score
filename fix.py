f = open('templates/game.html', encoding='utf-8')
c = f.read()
f.close()

old = '<button class="btn btn-ghost btn-sm" onclick="openSprayModal()">Spray Chart</button>'
new = '<button class="btn btn-ghost btn-sm" onclick="openSprayModal()">Spray Chart</button>\n      <a href="/pitch/{{ game.id }}" class="btn btn-ghost btn-sm">Pitch Tracker &#8594;</a>'

if old in c:
    c = c.replace(old, new)
    f = open('templates/game.html', 'w', encoding='utf-8')
    f.write(c)
    f.close()
    print('Fixed!')
else:
    print('Pattern not found')

