import math
import os
import shutil
import struct
from PIL import Image, ImageOps
from psd_tools import PSDImage
from hacktools import common


# Font
def getFontGlyphs(file):
    glyphs = {}
    with common.Stream(file, "rb") as f:
        # Header
        f.seek(25)
        fontheight = f.readByte()
        f.seek(3, 1)
        fontwidth = f.readByte()
        f.seek(2, 1)
        plgcoffset = f.readUInt()
        hdwcoffset = f.readUInt()
        pamcoffset = f.readUInt()
        common.logDebug("fontwidth:", fontwidth, "fontheight:", fontheight, "plgcoffset:", plgcoffset, "hdwcoffset:", hdwcoffset, "pamcoffset:", pamcoffset)
        # PLGC
        f.seek(plgcoffset - 4)
        plgcsize = f.readUInt()
        f.seek(2, 1)
        tilelength = f.readUShort()
        tilenum = (plgcsize - 0x10) // tilelength
        common.logDebug("plgcsize:", plgcsize, "tilelength:", tilelength, "tilenum:", tilenum)
        # HDWC
        f.seek(hdwcoffset)
        firstcode = f.readUShort()
        lastcode = f.readUShort()
        f.seek(4, 1)
        common.logDebug("firstcode:", firstcode, "lastcode:", lastcode)
        hdwc = []
        for i in range(tilenum):
            hdwcstart = f.readSByte()
            hdwcwidth = f.readByte()
            hdwclength = f.readByte()
            hdwc.append((hdwcstart, hdwcwidth, hdwclength))
        # PAMC
        nextoffset = pamcoffset
        while nextoffset != 0x00:
            f.seek(nextoffset)
            firstchar = f.readUShort()
            lastchar = f.readUShort()
            sectiontype = f.readUInt()
            nextoffset = f.readUInt()
            common.logDebug("firstchar:", common.toHex(firstchar), "lastchar:", common.toHex(lastchar), "sectiontype:", sectiontype, "nextoffset:", nextoffset)
            if sectiontype == 0:
                firstcode = f.readUShort()
                for i in range(lastchar - firstchar + 1):
                    c = codeToChar(firstchar + i)
                    glyphs[c] = hdwc[firstcode + i] + (firstchar + i,)
            elif sectiontype == 1:
                for i in range(lastchar - firstchar + 1):
                    charcode = f.readUShort()
                    if charcode == 0xFFFF or charcode >= len(hdwc):
                        continue
                    c = codeToChar(firstchar + i)
                    glyphs[c] = hdwc[charcode] + (firstchar + i,)
            else:
                common.logError("Unknown section type", sectiontype)
    return glyphs


def codeToChar(code):
    try:
        if code < 256:
            return struct.pack("B", code).decode("ascii")
        return struct.pack(">H", code).decode("shift_jis")
    except UnicodeDecodeError:
        return ""


# Graphics
class NCGR:
    width = 0
    height = 0
    bpp = 4
    tilesize = 8
    lineal = False
    tiles = []


class NSCR:
    width = 0
    height = 0
    maplen = 0
    mapoffset = 0
    maps = []


class Map:
    pal = 0
    xflip = False
    yflip = False
    tile = 0


class NCER:
    tbank = 0
    bankoffset = 0
    blocksize = 0
    partitionoffset = 0
    maxpartitionsize = 0
    firstpartitionoffset = 0
    banks = []


class Bank:
    cellnum = 0
    cellinfo = 0
    celloffset = 0
    partitionoffset = 0
    partitionsize = 0
    cells = []
    xmax = 0
    ymax = 0
    xmin = 0
    ymin = 0
    width = 0
    height = 0
    layernum = 0
    duplicate = False


class Cell:
    x = 0
    y = 0
    width = 0
    height = 0
    numcell = 0
    shape = 0
    size = 0
    tileoffset = 0
    rsflag = False
    objdisable = False
    doublesize = False
    objmode = 0
    mosaic = False
    depth = False
    xflip = False
    yflip = False
    selectparam = 0
    priority = 0
    pal = 0
    layer = -1


def readNitroGraphic(palettefile, tilefile, mapfile, cellfile):
    if not os.path.isfile(palettefile):
        common.logError("Palette", palettefile, "not found")
        return [], None, [], None, 0, 0
    palettes = readNCLR(palettefile)
    # Read tiles
    ncgr = readNCGR(tilefile)
    width = ncgr.width
    height = ncgr.height
    # Read maps
    nscr = None
    if os.path.isfile(mapfile):
        nscr = readNSCR(mapfile)
        width = nscr.width
        height = nscr.height
    # Read banks
    ncer = None
    if os.path.isfile(cellfile):
        ncer = readNCER(cellfile)
    return palettes, ncgr, nscr, ncer, width, height


def readNCLR(nclrfile):
    palettes = []
    with common.Stream(nclrfile, "rb") as f:
        # Read header
        f.seek(14)
        sections = f.readUShort()
        f.seek(20)
        length = f.readUInt()
        bpp = 8 if f.readUShort() == 0x04 else 4
        f.seek(6, 1)  # 0x00
        pallen = f.readUInt()
        if pallen == 0 or pallen > length:
            pallen = length - 0x18
        offset = f.readUInt()
        colornum = 0x10 if bpp == 4 else 0x100
        if pallen // 2 < colornum:
            colornum = pallen // 2
        common.logDebug("bpp", bpp, "length", length, "pallen", pallen, "colornum", colornum)
        # Read palettes
        f.seek(0x18 + offset)
        for i in range(pallen // (colornum * 2)):
            palette = []
            for j in range(colornum):
                palette.append(common.readPalette(f.readUShort()))
            palettes.append(palette)
        # Read index
        if sections == 2:
            f.seek(16, 1)
            indexedpalettes = {}
            for i in range(len(palettes)):
                indexedpalettes[f.readUShort()] = palettes[i]
        else:
            indexedpalettes = {i: palettes[i] for i in range(0, len(palettes))}
    common.logDebug("Loaded", len(indexedpalettes), "palettes")
    return indexedpalettes


def readNCGR(ncgrfile):
    ncgr = NCGR()
    ncgr.tiles = []
    with common.Stream(ncgrfile, "rb") as f:
        f.seek(24)
        ncgr.height = f.readUShort()
        ncgr.width = f.readUShort()
        ncgr.bpp = 8 if f.readUInt() == 0x04 else 4
        ncgr.tilesize = 8
        f.seek(4, 1)
        flag = f.readUInt()
        ncgr.lineal = (flag & 0xFF) != 0x00
        ncgr.tilelen = f.readUInt()
        f.seek(4, 1)
        ncgr.tileoffset = f.tell()
        tiledata = f.read(ncgr.tilelen)
        if ncgr.width != 0xFFFF:
            ncgr.width *= ncgr.tilesize
            ncgr.height *= ncgr.tilesize
        common.logDebug(vars(ncgr))
        for i in range(ncgr.tilelen // (32 if ncgr.bpp == 4 else 64)):
            singletile = []
            for j in range(ncgr.tilesize * ncgr.tilesize):
                x = i * (ncgr.tilesize * ncgr.tilesize) + j
                if ncgr.bpp == 4:
                    index = (tiledata[x // 2] >> ((x % 2) << 2)) & 0x0f
                else:
                    index = tiledata[x]
                singletile.append(index)
            ncgr.tiles.append(singletile)
    common.logDebug("Loaded", len(ncgr.tiles), "tiles")
    return ncgr


def readNSCR(nscrfile):
    nscr = NSCR()
    nscr.maps = []
    with common.Stream(nscrfile, "rb") as f:
        f.seek(24)
        nscr.width = f.readUShort()
        nscr.height = f.readUShort()
        f.seek(4, 1)
        nscr.maplen = f.readUInt()
        nscr.mapoffset = f.tell()
        mapdata = f.read(nscr.maplen)
        common.logDebug(vars(nscr))
        for i in range(0, len(mapdata), 2):
            map = Map()
            data = struct.unpack("<h", mapdata[i:i+2])[0]
            map.pal = (data >> 12) & 0xF
            map.xflip = (data >> 10) & 1
            map.yflip = (data >> 11) & 1
            map.tile = data & 0x3FF
            nscr.maps.append(map)
    common.logDebug("Loaded", len(nscr.maps), "maps")
    return nscr


def readNCER(ncerfile):
    ncer = NCER()
    ncer.banks = []
    with common.Stream(ncerfile, "rb") as f:
        f.seek(24)
        ncer.banknum = f.readUShort()
        ncer.tbank = f.readUShort()
        ncer.bankoffset = f.readUInt()
        ncer.blocksize = f.readUInt() & 0xFF
        ncer.partitionoffset = f.readUInt()
        for i in range(ncer.banknum):
            bank = Bank()
            bank.cells = []
            ncer.banks.append(bank)
        # Partition data
        if ncer.partitionoffset > 0:
            f.seek(16 + ncer.partitionoffset + 8)
            ncer.maxpartitionsize = f.readUInt()
            ncer.firstpartitionoffset = f.readUInt()
            f.seek(ncer.firstpartitionoffset - 8, 1)
            for i in range(ncer.banknum):
                ncer.banks[i].partitionoffset = f.readUInt()
                ncer.banks[i].partitionsize = f.readUInt()
        common.logDebug(vars(ncer))
        f.seek(16 + ncer.bankoffset + 8)
        for i in range(len(ncer.banks)):
            bank = ncer.banks[i]
            bank.cellnum = f.readUShort()
            bank.cellinfo = f.readUShort()
            bank.celloffset = f.readUInt()
            if ncer.tbank == 0x01:
                bank.xmax = f.readShort()
                bank.ymax = f.readShort()
                bank.xmin = f.readShort()
                bank.ymin = f.readShort()
                bank.width = bank.xmax - bank.xmin + 1
                bank.height = bank.ymax - bank.ymin + 1
            pos = f.tell()
            f.seek(pos + (ncer.banknum - (i + 1)) * (8 if ncer.tbank == 0x00 else 0x10) + bank.celloffset)
            for j in range(bank.cellnum):
                obj0 = f.readUShort()
                obj1 = f.readUShort()
                obj2 = f.readUShort()
                cell = Cell()
                cell.y = obj0 & 0xFF
                if cell.y >= 128:
                    cell.y -= 256
                cell.shape = (obj0 >> 14) & 3
                cell.x = obj1 & 0x01FF
                if cell.x >= 0x100:
                    cell.x -= 0x200
                cell.size = (obj1 >> 14) & 3
                cell.tileoffset = obj2 & 0x03FF
                cell.rsflag = ((obj0 >> 8) & 1) == 1
                if not cell.rsflag:
                    cell.objdisable = ((obj0 >> 9) & 1) == 1
                else:
                    cell.doublesize = ((obj0 >> 9) & 1) == 1
                cell.objmode = (obj0 >> 10) & 3
                cell.mosaic = ((obj0 >> 12) & 1) == 1
                cell.depth = ((obj0 >> 13) & 1) == 1
                if not cell.rsflag:
                    # cell.unused = (obj1 >> 9) & 7
                    cell.xflip = ((obj1 >> 12) & 1) == 1
                    cell.yflip = ((obj1 >> 13) & 1) == 1
                else:
                    cell.selectparam = (obj1 >> 9) & 0x1F
                cell.priority = (obj2 >> 10) & 3
                cell.pal = (obj2 >> 12) & 0xF
                if cell.shape == 0:
                    if cell.size == 0:
                        cellsize = (8, 8)
                    elif cell.size == 1:
                        cellsize = (16, 16)
                    elif cell.size == 2:
                        cellsize = (32, 32)
                    elif cell.size == 3:
                        cellsize = (64, 64)
                elif cell.shape == 1:
                    if cell.size == 0:
                        cellsize = (16, 8)
                    elif cell.size == 1:
                        cellsize = (32, 8)
                    elif cell.size == 2:
                        cellsize = (32, 16)
                    elif cell.size == 3:
                        cellsize = (64, 32)
                elif cell.shape == 2:
                    if cell.size == 0:
                        cellsize = (8, 16)
                    elif cell.size == 1:
                        cellsize = (8, 32)
                    elif cell.size == 2:
                        cellsize = (16, 32)
                    elif cell.size == 3:
                        cellsize = (32, 64)
                cell.width = cellsize[0]
                cell.height = cellsize[1]
                cell.numcell = j
                bank.cells.append(cell)
            # Calculate bank size
            minx = miny = 512
            maxx = maxy = -512
            for cell in bank.cells:
                minx = min(minx, cell.x)
                miny = min(miny, cell.y)
                maxx = max(maxx, cell.x + cell.width)
                maxy = max(maxy, cell.y + cell.height)
            if ncer.tbank == 0x00:
                bank.width = maxx - minx
                bank.height = maxy - miny
            for cell in bank.cells:
                cell.x -= minx
                cell.y -= miny
            common.logDebug(vars(bank))
            # Sort cells based on priority
            bank.cells.sort(key=lambda x: (x.priority, x.numcell), reverse=True)
            f.seek(pos)
            # Calculate layers for .psd exporting, first put the first cell on the first layer
            cells = sorted(bank.cells, key=lambda x: (x.priority, x.numcell))
            if bank.cellnum > 0:
                bank.layernum = 1
                cells[0].layer = 0
                if len(cells) > 1:
                    for j in range(1, len(cells)):
                        cell = cells[j]
                        # For every other cell in the current layer, check if it's intersected
                        hit = False
                        for layercheck in cells:
                            if cell != layercheck and layercheck.layer == bank.layernum - 1:
                                if cellIntersect(cell, layercheck):
                                    hit = True
                                    break
                        if hit:
                            # All layers are full, make a new one
                            cells[j].layer = bank.layernum
                            bank.layernum += 1
                        else:
                            cells[j].layer = bank.layernum - 1
    # Mark banks as duplicate
    for bank in ncer.banks:
        if bank.duplicate:
            continue
        for bank2 in ncer.banks:
            if bank2.duplicate or bank == bank2 or bank.cellnum != bank2.cellnum:
                continue
            samecells = True
            for i in range(bank.cellnum):
                if bank.cells[i].width != bank2.cells[i].width or bank.cells[i].height != bank2.cells[i].height or bank.cells[i].tileoffset != bank2.cells[i].tileoffset:
                    samecells = False
                    break
            if samecells:
                bank2.duplicate = True
    common.logDebug("Loaded", len(ncer.banks), "banks")
    return ncer


def cellIntersect(a, b):
    return (a.x < b.x + b.width) and (a.x + a.width > b.x) and (a.y < b.y + b.height) and (a.y + a.height > b.y)


def tileToPixels(pixels, width, ncgr, tile, i, j, palette, pali, usetrasp=True):
    for i2 in range(ncgr.tilesize):
        for j2 in range(ncgr.tilesize):
            try:
                index = ncgr.tiles[tile][i2 * ncgr.tilesize + j2]
                if not usetrasp or index > 0:
                    if ncgr.lineal:
                        lineal = (i * width * ncgr.tilesize) + (j * ncgr.tilesize * ncgr.tilesize) + (i2 * ncgr.tilesize + j2)
                        pixelx = lineal % width
                        pixely = int(math.floor(lineal / width))
                    else:
                        pixelx = j * ncgr.tilesize + j2
                        pixely = i * ncgr.tilesize + i2
                    pixels[pixelx, pixely] = palette[pali + index]
            except IndexError:
                common.logWarning("Unable to set pixels at", i, j, i2, j2, "for tile", tile, "with palette", pali)
    return pixels


def drawNCER(outfile, ncer, ncgr, palettes, usetrasp=True, layered=False):
    palsize = 0
    for palette in palettes.values():
        palsize += 5 * (len(palette) // 8)
    width = height = 0
    for bank in ncer.banks:
        if bank.duplicate:
            continue
        width = max(width, bank.width)
        height += bank.height
    img = Image.new("RGBA", (width + 40, max(height, palsize)), (0, 0, 0, 0))
    pixels = img.load()
    # Draw palette
    palstart = 0
    for palette in palettes.values():
        pixels = common.drawPalette(pixels, palette, width, palstart * 10)
        palstart += 1
    layers = []
    # If all banks have a single layer, disable layering
    if layered:
        allone = True
        for bank in ncer.banks:
            if bank.layernum > 1:
                allone = False
                break
        layered = not allone
    # Save just the palette as a separate layer
    if layered:
        img.save(outfile, "PNG")
    # Loop and draw the banks
    currheight = 0
    for bankn in range(len(ncer.banks)):
        bank = ncer.banks[bankn]
        if bank.width == 0 or bank.height == 0 or bank.duplicate:
            continue
        if layered:
            banklayers = []
            for i in range(bank.layernum):
                banklayers.append(Image.new("RGBA", (img.width, img.height), (0, 0, 0, 0)))
        for celln in range(len(bank.cells)):
            cell = bank.cells[celln]
            x = (bank.partitionoffset // (32 * (ncgr.bpp // 4))) + (cell.tileoffset << ncer.blocksize // (ncgr.bpp // 4))
            if cell.pal in palettes.keys():
                pali = 0
                palette = palettes[cell.pal]
            else:
                pali = cell.pal * 16
                palette = palettes[0]
            cellimg = Image.new("RGBA", (cell.width, cell.height), (0, 0, 0, 0))
            cellpixels = cellimg.load()
            for i in range(cell.height // ncgr.tilesize):
                for j in range(cell.width // ncgr.tilesize):
                    cellpixels = tileToPixels(cellpixels, cell.width, ncgr, x, i, j, palette, pali, usetrasp)
                    x += 1
            if cell.xflip or cell.yflip:
                if cell.yflip:
                    cellimg = ImageOps.flip(cellimg)
                if cell.xflip:
                    cellimg = ImageOps.mirror(cellimg)
            if layered:
                banklayers[cell.layer].paste(cellimg, (cell.x, currheight + cell.y), cellimg)
            img.paste(cellimg, (cell.x, currheight + cell.y), cellimg)
        if layered:
            for i in range(bank.layernum):
                layerfile = outfile.replace(".png", "_" + str(bankn) + "_" + str(i) + ".png")
                banklayers[i].save(layerfile, "PNG")
                layers.append(layerfile)
        currheight += bank.height
    if layered and shutil.which("magick"):
        cmd = shutil.which("magick") + " convert ( -page +0+0 -label \"palette\" \"" + outfile + "\"[0] -background none -mosaic -set colorspace RGBA )"
        for layer in layers:
            cmd += " ( -page +0+0 -label \"" + os.path.basename(layer).replace(".png", "") + "\" \"" + layer + "\"[0] -background none -mosaic -set colorspace RGBA )"
        cmd += " ( -clone 0--1 -background none -mosaic ) -reverse \"" + outfile.replace(".png", ".psd") + "\""
        common.execute(cmd, False)
        for layer in layers:
            os.remove(layer)
        os.remove(outfile)
    img.save(outfile, "PNG")


def drawNCGR(outfile, nscr, ncgr, palettes, width, height, usetrasp=True):
    palsize = 0
    for palette in palettes.values():
        palsize += 5 * (len(palette) // 8)
    img = Image.new("RGBA", (width + 40, max(height, palsize)), (0, 0, 0, 0))
    pixels = img.load()
    x = 0
    for i in range(height // ncgr.tilesize):
        for j in range(width // ncgr.tilesize):
            if nscr is not None:
                map = nscr.maps[x]
                if map.pal in palettes.keys():
                    pali = 0
                    palette = palettes[map.pal]
                else:
                    pali = map.pal * 16
                    palette = palettes[0]
                pixels = tileToPixels(pixels, width, ncgr, map.tile, i, j, palette, pali, usetrasp)
                # Very inefficient way to flip pixels
                if map.xflip or map.yflip:
                    sub = img.crop(box=(j * ncgr.tilesize, i * ncgr.tilesize, j * ncgr.tilesize + ncgr.tilesize, i * ncgr.tilesize + ncgr.tilesize))
                    if map.yflip:
                        sub = ImageOps.flip(sub)
                    if map.xflip:
                        sub = ImageOps.mirror(sub)
                    img.paste(sub, box=(j * ncgr.tilesize, i * ncgr.tilesize))
            else:
                pixels = tileToPixels(pixels, width, ncgr, x, i, j, palettes[0], 0, usetrasp)
            x += 1
    palstart = 0
    for palette in palettes.values():
        pixels = common.drawPalette(pixels, palette, width, palstart * 10)
        palstart += 1
    img.save(outfile, "PNG")


def writeNCGRData(f, bpp, index1, index2):
    if bpp == 4:
        f.writeByte(((index2) << 4) | index1)
    else:
        f.writeByte(index1)
        f.writeByte(index2)


def writeNCGRTile(f, pixels, ncgr, i, j, palette):
    for i2 in range(ncgr.tilesize):
        for j2 in range(0, ncgr.tilesize, 2):
            index1 = common.getPaletteIndex(palette, pixels[j * ncgr.tilesize + j2, i * ncgr.tilesize + i2])
            index2 = common.getPaletteIndex(palette, pixels[j * ncgr.tilesize + j2 + 1, i * ncgr.tilesize + i2])
            writeNCGRData(f, ncgr.bpp, index1, index2)


def writeNCGR(file, ncgr, infile, palettes, width=-1, height=-1):
    if width < 0:
        width = ncgr.width
        height = ncgr.height
    img = Image.open(infile)
    img = img.convert("RGBA")
    pixels = img.load()
    with common.Stream(file, "rb+") as f:
        f.seek(ncgr.tileoffset)
        for i in range(height // ncgr.tilesize):
            for j in range(width // ncgr.tilesize):
                writeNCGRTile(f, pixels, ncgr, i, j, palettes[0])


def writeNSCR(file, ncgr, nscr, infile, palettes, width=-1, height=-1):
    if width < 0:
        width = nscr.width
        # height = nscr.height
    img = Image.open(infile)
    img = img.convert("RGBA")
    pixels = img.load()
    with common.Stream(file, "rb+") as f:
        donetiles = []
        x = 0
        for i in range(height // ncgr.tilesize):
            for j in range(width // ncgr.tilesize):
                map = nscr.maps[x]
                # Skip flipped tiles since there's always(?) going to be an unflipped one next
                if map.xflip or map.yflip:
                    continue
                # Write the tile if it's a new one
                if map.tile not in donetiles:
                    donetiles.append(map.tile)
                    f.seek(ncgr.tileoffset + map.tile * (32 * (ncgr.bpp // 4)))
                    writeNCGRTile(f, pixels, ncgr, i, j, palettes[map.pal])
                x += 1


def writeNCER(file, ncgr, ncer, infile, palettes):
    psd = infile.endswith(".psd")
    if psd:
        psd = PSDImage.open(infile)
        basename = os.path.basename(infile).replace(".psd", "")
    else:
        img = Image.open(infile)
        img = img.convert("RGBA")
        pixels = img.load()
    with common.Stream(file, "rb+") as f:
        currheight = 0
        donetiles = []
        for nceri in range(len(ncer.banks)):
            bank = ncer.banks[nceri]
            if bank.width == 0 or bank.height == 0 or bank.duplicate:
                continue
            if psd:
                # Extract layers from the psd file, searching them by name
                layers = []
                for i in range(bank.layernum):
                    layername = basename + "_" + str(nceri) + "_" + str(i)
                    psdlayer = None
                    for layer in psd:
                        if layer.name == layername:
                            psdlayer = layer
                            break
                    if psdlayer is None:
                        common.logError("Layer", layername, "not found")
                        return
                    # Copy the layer in a normal PIL image for cell access, since the layer is cropped
                    layerimg = Image.new("RGBA", (psd.width, psd.height), (0, 0, 0, 0))
                    psdimg = psdlayer.topil()
                    layerimg.paste(psdimg, (psdlayer.left, psdlayer.top), psdimg)
                    layers.append(layerimg)
            for cell in bank.cells:
                # Skip flipped cells since there's always(?) going to be an unflipped one next
                if cell.xflip or cell.yflip:
                    continue
                if psd:
                    pixels = layers[cell.layer].load()
                tile = (bank.partitionoffset // (32 * (ncgr.bpp // 4))) + (cell.tileoffset << ncer.blocksize // (ncgr.bpp // 4))
                if cell.pal in palettes.keys():
                    pali = 0
                    palette = palettes[cell.pal]
                else:
                    pali = cell.pal * 16
                    palette = palettes[0]
                for i in range(cell.height // ncgr.tilesize):
                    for j in range(cell.width // ncgr.tilesize):
                        if tile not in donetiles:
                            donetiles.append(tile)
                            f.seek(ncgr.tileoffset + tile * (32 * (ncgr.bpp // 4)))
                            for i2 in range(ncgr.tilesize):
                                for j2 in range(0, ncgr.tilesize, 2):
                                    pixelx = cell.x + j * ncgr.tilesize + j2
                                    pixely = currheight + cell.y + i * ncgr.tilesize + i2
                                    index1 = common.getPaletteIndex(palette, pixels[pixelx, pixely], False, pali, 16 if ncgr.bpp == 4 else -1)
                                    index2 = common.getPaletteIndex(palette, pixels[pixelx + 1, pixely], False, pali, 16 if ncgr.bpp == 4 else -1)
                                    writeNCGRData(f, ncgr.bpp, index1, index2)
                        tile += 1
            currheight += bank.height


# 3D Models
NSBMDbpp = [0, 8, 2, 4, 8, 2, 8, 16]


class NSBMD:
    textures = []
    palettes = []
    blocksize = 0
    blocklimit = 0
    texdatasize = 0
    texdataoffset = 0
    sptexsize = 0
    sptexoffset = 0
    spdataoffset = 0
    paldatasize = 0
    paldefoffset = 0
    paldataoffset = 0


class NSBMDTexture:
    name = ""
    offset = 0
    format = 0
    width = 0
    height = 0
    size = 0
    data = []
    spdata = []


class NSBMDPalette:
    name = ""
    offset = 0
    size = 0
    data = []


def readNSBMD(nsbmdfile):
    nsbmd = NSBMD()
    with common.Stream(nsbmdfile, "rb") as f:
        # Read the TEX0 offset
        f.seek(20)
        texstart = f.readUShort()
        # If texstart points to MDL0, the model doesn't have any texture
        if texstart == 17485:  # MDL0
            return None
        nsbmd.blockoffset = texstart
        # Read TEX0 block
        f.seek(nsbmd.blockoffset + 4)
        nsbmd.blocksize = f.readUInt()
        nsbmd.blocklimit = nsbmd.blocksize + nsbmd.blockoffset
        f.seek(4, 1)
        nsbmd.texdatasize = f.readUShort() * 8
        f.seek(6, 1)
        nsbmd.texdataoffset = f.readUInt() + nsbmd.blockoffset
        f.seek(4, 1)
        nsbmd.sptexsize = f.readUShort() * 8
        f.seek(6, 1)
        nsbmd.sptexoffset = f.readUInt() + nsbmd.blockoffset
        nsbmd.spdataoffset = f.readUInt() + nsbmd.blockoffset
        f.seek(4, 1)
        nsbmd.paldatasize = f.readUShort() * 8
        f.seek(2, 1)
        nsbmd.paldefoffset = f.readUInt() + nsbmd.blockoffset
        nsbmd.paldataoffset = f.readUInt() + nsbmd.blockoffset
        common.logDebug(vars(nsbmd))
        # Texture definition
        f.seek(1, 1)
        texnum = f.readByte()
        pos = f.tell()
        f.seek(nsbmd.paldefoffset + 1)
        palnum = f.readByte()
        f.seek(pos)
        common.logDebug("texnum:", texnum, "palnum:", palnum)
        f.seek(14 + (texnum * 4), 1)
        nsbmd.textures = []
        nsbmd.palettes = []
        for i in range(texnum):
            offset = f.readUShort() * 8
            param = f.readUShort()
            f.seek(4, 1)
            tex = NSBMDTexture()
            tex.format = (param >> 10) & 7
            tex.width = 8 << ((param >> 4) & 7)
            tex.height = 8 << ((param >> 7) & 7)
            tex.size = tex.width * tex.height * NSBMDbpp[tex.format] // 8
            if tex.format == 5:
                tex.offset = offset + nsbmd.sptexoffset
            else:
                tex.offset = offset + nsbmd.texdataoffset
            nsbmd.textures.append(tex)
        # Texture name
        for tex in nsbmd.textures:
            tex.name = f.readString(16)
            common.logDebug(vars(tex))
        # Palette definition
        f.seek(nsbmd.paldefoffset + 2 + 14 + (palnum * 4))
        for i in range(palnum):
            pal = NSBMDPalette()
            pal.offset = (f.readUShort() * 8) + nsbmd.paldataoffset
            f.seek(2, 1)
            nsbmd.palettes.append(pal)
        # Palette size
        if palnum > 0:
            for i in range(palnum):
                r = i + 1
                while r < len(nsbmd.palettes) and nsbmd.palettes[r].offset == nsbmd.palettes[i].offset:
                    r += 1
                if r != palnum:
                    nsbmd.palettes[i].size = nsbmd.palettes[r].offset - nsbmd.palettes[i].offset
                else:
                    nsbmd.palettes[i].size = nsbmd.blocklimit - nsbmd.palettes[i].offset
            nsbmd.palettes[i].size = nsbmd.blocklimit - nsbmd.palettes[i].offset
        # Palette name
        for pal in nsbmd.palettes:
            pal.name = f.readString(16)
            common.logDebug(vars(pal))
        # Traverse palettes
        for pal in nsbmd.palettes:
            f.seek(pal.offset)
            pal.data = []
            for i in range(pal.size // 2):
                pal.data.append(common.readPalette(f.readShort()))
        # Traverse texture
        spdataoffset = nsbmd.spdataoffset
        for texi in range(len(nsbmd.textures)):
            tex = nsbmd.textures[texi]
            if tex.format == 5:
                r = tex.size >> 1
                f.seek(spdataoffset)
                tex.spdata = []
                for i in range(r // 2):
                    tex.spdata.append(f.readUShort())
                spdataoffset += r
            # Export texture
            f.seek(tex.offset)
            if tex.format == 5:
                tex.data = []
                for i in range(tex.size // 4):
                    tex.data.append(f.readUInt())
            else:
                tex.data = f.read(tex.size)
        return nsbmd


def drawNSBMD(file, nsbmd, texi):
    tex = nsbmd.textures[texi]
    common.logDebug("Exporting", tex.name, "...")
    palette = None
    if tex.format != 7:
        palette = nsbmd.palettes[texi].data if texi < len(nsbmd.palettes) else nsbmd.palettes[0].data
        img = Image.new("RGBA", (tex.width + 40, max(tex.height, (len(palette) // 8) * 5)), (0, 0, 0, 0))
    else:
        img = Image.new("RGBA", (tex.width, tex.height), (0, 0, 0, 0))
    pixels = img.load()
    # A3I5 Translucent Texture (3bit Alpha, 5bit Color Index)
    if tex.format == 1:
        for i in range(tex.height):
            for j in range(tex.width):
                x = i * tex.width + j
                index = tex.data[x] & 0x1f
                alpha = (tex.data[x] >> 5) & 7
                alpha = ((alpha * 4) + (alpha // 2)) << 3
                if index < len(palette):
                    pixels[j, i] = (palette[index][0], palette[index][1], palette[index][2], alpha)
                else:
                    common.logWarning("Index", index, "is out of range", len(palette))
    # 4-color Palette
    elif tex.format == 2:
        for i in range(tex.height):
            for j in range(tex.width):
                x = i * tex.width + j
                index = (tex.data[x // 4] >> ((x % 4) << 1)) & 3
                if index < len(palette):
                    pixels[j, i] = palette[index]
                else:
                    common.logWarning("Index", index, "is out of range", len(palette))
    # 16-color Palette
    elif tex.format == 3:
        for i in range(tex.height):
            for j in range(tex.width):
                x = i * tex.width + j
                index = (tex.data[x // 2] >> ((x % 2) << 2)) & 0x0f
                if index < len(palette):
                    pixels[j, i] = palette[index]
                else:
                    common.logWarning("Index", index, "is out of range", len(palette))
    # 256-color Palette
    elif tex.format == 4:
        for i in range(tex.height):
            for j in range(tex.width):
                x = i * tex.width + j
                index = tex.data[x]
                if index < len(palette):
                    pixels[j, i] = palette[index]
                else:
                    common.logWarning("Index", index, "is out of range", len(palette))
    # 4x4-Texel Compressed Texture
    elif tex.format == 5:
        w = tex.width // 4
        h = tex.height // 4
        for y in range(h):
            for x in range(w):
                index = y * w + x
                t = tex.data[index]
                d = tex.spdata[index]
                addr = d & 0x3fff
                pali = addr << 1
                mode = (d >> 14) & 3
                for r in range(4):
                    for c in range(4):
                        texel = (t >> ((r * 4 + c) * 2)) & 3
                        i = y * 4 + r
                        j = x * 4 + c
                        try:
                            if mode == 0:
                                if texel == 3:
                                    pixels[j, i] = (0xff, 0xff, 0xff, 0)
                                else:
                                    pixels[j, i] = palette[pali + texel]
                            elif mode == 2:
                                pixels[j, i] = palette[pali + texel]
                            elif mode == 1:
                                if texel == 0 or texel == 1:
                                    pixels[j, i] = palette[pali + texel]
                                elif texel == 2:
                                    pixels[j, i] = common.sumColors(palette[pali], palette[pali + 1])
                                elif texel == 3:
                                    pixels[j, i] = (0xff, 0xff, 0xff, 0)
                            elif mode == 3:
                                if texel == 0 or texel == 1:
                                    pixels[j, i] = palette[pali + texel]
                                elif texel == 2:
                                    pixels[j, i] = common.sumColors(palette[pali], palette[pali + 1], 5, 3, 8)
                                elif texel == 3:
                                    pixels[j, i] = common.sumColors(palette[pali], palette[pali + 1], 3, 5, 8)
                        except IndexError:
                            pixels[j, i] = (0x00, 0x00, 0x00, 0xff)
    # A5I3 Translucent Texture (5bit Alpha, 3bit Color Index)
    elif tex.format == 6:
        for i in range(tex.height):
            for j in range(tex.width):
                x = i * tex.width + j
                index = tex.data[x] & 0x7
                alpha = (tex.data[x] >> 3) & 0x1f
                alpha = ((alpha * 4) + (alpha // 2)) << 3
                if index < len(palette):
                    pixels[j, i] = (palette[index][0], palette[index][1], palette[index][2], alpha)
                else:
                    common.logWarning("Index", index, "is out of range", len(palette))
    # Direct Color Texture
    elif tex.format == 7:
        for i in range(tex.height):
            for j in range(tex.width):
                x = i * tex.width + j
                p = tex.data[x * 2] + (tex.data[x * 2 + 1] << 8)
                pixels[j, i] = (((p >> 0) & 0x1f) << 3, ((p >> 5) & 0x1f) << 3, ((p >> 10) & 0x1f) << 3, 0xff if (p & 0x8000) else 0)
    # Draw palette
    if tex.format != 7:
        pixels = common.drawPalette(pixels, palette, tex.width)
    img.save(file, "PNG")
