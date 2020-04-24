import codecs
from enum import IntFlag
import os
import struct
import crcmod
from ndspy import codeCompression
from hacktools import common, compression


def extractRom(romfile, extractfolder, workfolder=""):
    common.logMessage("Extracting ROM", romfile, "...")
    ndstool = common.bundledFile("ndstool.exe")
    if not os.path.isfile(ndstool):
        common.logError("ndstool not found")
    else:
        common.makeFolder(extractfolder)
        common.execute(ndstool + " -x {rom} -9 {folder}arm9.bin -7 {folder}arm7.bin -y9 {folder}y9.bin -y7 {folder}y7.bin -t {folder}banner.bin -h {folder}header.bin -d {folder}data -y {folder}overlay".
                       format(rom=romfile, folder=extractfolder), False)
        if workfolder != "":
            common.copyFolder(extractfolder, workfolder)
        common.logMessage("Done!")


def repackRom(romfile, rompatch, workfolder, patchfile=""):
    common.logMessage("Repacking ROM", rompatch, "...")
    ndstool = common.bundledFile("ndstool.exe")
    if not os.path.isfile(ndstool):
        common.logError("ndstool not found")
    else:
        common.execute(ndstool + " -c {rom} -9 {folder}arm9.bin -7 {folder}arm7.bin -y9 {folder}y9.bin -y7 {folder}y7.bin -t {folder}banner.bin -h {folder}header.bin -d {folder}data -y {folder}overlay".
                       format(rom=rompatch, folder=workfolder), False)
        common.logMessage("Done!")
        # Create xdelta patch
        if patchfile != "":
            common.logMessage("Creating xdelta patch", patchfile, "...")
            xdelta = common.bundledFile("xdelta.exe")
            if not os.path.isfile(xdelta):
                common.logError("xdelta not found")
            else:
                common.execute(xdelta + " -f -e -s {rom} {rompatch} {patch}".format(rom=romfile, rompatch=rompatch, patch=patchfile), False)
                common.logMessage("Done!")


def editBannerTitle(file, title):
    with common.Stream(file, "r+b") as f:
        for i in range(6):
            # Write new text for all languages
            f.seek(576 + 256 * i)
            for char in title:
                f.writeByte(ord(char))
                f.writeByte(0x00)
            # Compute CRC
            f.seek(32)
            crc = crcmod.predefined.mkCrcFun("modbus")(f.read(2080))
            f.seek(2)
            f.writeUShort(crc)


def getHeaderID(file):
    with common.Stream(file, "rb") as f:
        f.seek(12)
        return f.readString(6)


# Binary-related functions
def extractBIN(range, detectFunc=common.detectEncodedString, encoding="shift_jis", binin="data/extract/arm9.bin", binfile="data/bin_output.txt"):
    common.logMessage("Extracting BIN to", binfile, "...")
    foundstrings = extractBinaryStrings(binin, binfile, range, detectFunc, encoding)
    common.logMessage("Done! Extracted", len(foundstrings), "lines")


def extractBinaryStrings(infile, outfile, binrange, func=common.detectEncodedString, encoding="shift_jis", writepos=False):
    foundstrings = []
    insize = os.path.getsize(infile)
    with codecs.open(outfile, "w", "utf-8") as out:
        with common.Stream(infile, "rb") as f:
            f.seek(binrange[0])
            while f.tell() < binrange[1] and f.tell() < insize - 2:
                pos = f.tell()
                check = func(f, encoding)
                if check != "":
                    if check not in foundstrings:
                        common.logDebug("Found string at", pos)
                        foundstrings.append(check)
                        if writepos:
                            out.write(str(pos) + "!")
                        out.write(check + "=\n")
                    pos = f.tell() - 1
                f.seek(pos + 1)
    return foundstrings


def repackBIN(range, freeranges=None, detectFunc=common.detectEncodedString, writeFunc=common.writeEncodedString, encoding="shift_jis", comments="#", binin="data/extract/arm9.bin", binout="data/repack/arm9.bin", binfile="data/bin_input.txt"):
    if not os.path.isfile(binfile):
        common.logError("Input file", binfile, "not found")
        return False

    common.copyFile(binin, binout)
    common.logMessage("Repacking BIN from", binfile, "...")
    section = {}
    with codecs.open(binfile, "r", "utf-8") as bin:
        section = common.getSection(bin, "", comments)
        chartot, transtot = common.getSectionPercentage(section)
    repackBinaryStrings(section, binin, binout, range, freeranges, detectFunc, writeFunc, encoding)
    common.logMessage("Done! Translation is at {0:.2f}%".format((100 * transtot) / chartot))
    return True


def repackBinaryStrings(section, infile, outfile, binrange, freeranges=None, detectFunc=common.detectEncodedString, writeFunc=common.writeEncodedString, encoding="shift_jis"):
    insize = os.path.getsize(infile)
    with common.Stream(infile, "rb") as fi:
        currentrange = 0
        if freeranges is not None:
            rangepos = freeranges[currentrange][0]
            allbin = fi.read()
        strpointers = {}
        with common.Stream(outfile, "r+b") as fo:
            fi.seek(binrange[0])
            while fi.tell() < binrange[1] and fi.tell() < insize - 2:
                pos = fi.tell()
                check = detectFunc(fi, encoding)
                if check != "":
                    if check in section and section[check][0] != "":
                        common.logDebug("Replacing string at", pos)
                        newsjis = section[check][0]
                        if newsjis == "!":
                            newsjis = ""
                        fo.seek(pos)
                        endpos = fi.tell() - 1
                        newlen = writeFunc(fo, newsjis, endpos - pos + 1, encoding)
                        if newlen < 0:
                            if freeranges is None:
                                fo.writeZero(1)
                                common.logError("String", newsjis, "is too long.")
                            elif rangepos >= freeranges[currentrange][1] and newsjis not in strpointers:
                                common.logWarning("No more room! Skipping", newsjis, "...")
                            else:
                                # Write the string in a new portion of the rom
                                if newsjis in strpointers:
                                    newpointer = strpointers[newsjis]
                                else:
                                    common.logDebug("No room for the string, redirecting to", common.toHex(rangepos))
                                    fo.seek(rangepos)
                                    writeFunc(fo, newsjis)
                                    fo.writeZero(1)
                                    newpointer = 0x02000000 + rangepos
                                    rangepos = fo.tell()
                                    strpointers[newsjis] = newpointer
                                    if rangepos >= freeranges[currentrange][1]:
                                        if currentrange + 1 < len(freeranges):
                                            currentrange += 1
                                            rangepos = freeranges[currentrange][0]
                                # Search and replace the old pointer
                                pointer = 0x02000000 + pos
                                pointersearch = struct.pack("<I", pointer)
                                index = 0
                                common.logDebug("Searching for pointer", pointersearch.hex().upper())
                                while index < len(allbin):
                                    index = allbin.find(pointersearch, index)
                                    if index < 0:
                                        break
                                    common.logDebug("Replaced pointer at", str(index))
                                    fo.seek(index)
                                    fo.writeUInt(newpointer)
                                    index += 4
                        else:
                            fo.writeZero(endpos - fo.tell())
                    else:
                        pos = fi.tell() - 1
                fi.seek(pos + 1)


# Compression-related functions
class CompressionType(IntFlag):
    LZ10 = 0x10,
    LZ11 = 0x11,
    Huff4 = 0x24,
    Huff8 = 0x28,
    RLE = 0x30,
    LZ40 = 0x40,
    LZ60 = 0x60


def decompress(f, complength):
    header = f.readUInt()
    type = header & 0xFF
    decomplength = ((header & 0xFFFFFF00) >> 8)
    common.logDebug("Compression header:", common.toHex(header), "type:", common.toHex(type), "length:", decomplength)
    with common.Stream() as data:
        data.write(f.read(complength - 4))
        data.seek(0)
        if type == CompressionType.LZ10:
            return compression.decompressLZ10(data, complength, decomplength)
        elif type == CompressionType.LZ11:
            return compression.decompressLZ11(data, complength, decomplength)
        else:
            common.logError("Unsupported compression type", common.toHex(type))
            return data.read()


def compress(data, type):
    with common.Stream() as out:
        length = len(data)
        out.writeByte(type.value)
        out.writeByte(length & 0xFF)
        out.writeByte(length >> 8 & 0xFF)
        out.writeByte(length >> 16 & 0xFF)
        if type == CompressionType.LZ10:
            out.write(compression.compressLZ10(data))
        elif type == CompressionType.LZ11:
            out.write(compression.compressLZ11(data))
        else:
            common.logError("Unsupported compression type", common.toHex(type))
            out.write(data)
        out.seek(0)
        return out.read()


def decompressFile(infile, outfile):
    insize = os.path.getsize(infile)
    with common.Stream(infile, "rb") as fin:
        with common.Stream(outfile, "wb") as fout:
            fout.write(decompress(fin, insize - 4))


def compressFile(infile, outfile, type):
    with common.Stream(infile, "rb") as fin:
        data = fin.read()
        with common.Stream(outfile, "wb") as fout:
            fout.write(compress(data, type))


def decompressBinary(infile, outfile):
    with common.Stream(infile, "rb") as fin:
        data = fin.read()
    uncdata = codeCompression.decompress(data)
    with common.Stream(outfile, "wb") as f:
        f.write(uncdata)


def compressBinary(infile, outfile):
    with common.Stream(infile, "rb") as fin:
        data = bytearray(fin.read())
    compdata = bytearray(codeCompression.compress(data, True))
    codeoffset = 0
    for i in range(0, 0x8000, 4):
        if compdata[i:i+8] == b'\x21\x06\xC0\xDE\xDE\xC0\x06\x21':
            codeoffset = i - 0x1C
            break
    if codeoffset > 0:
        struct.pack_into("<I", compdata, codeoffset + 0x14, 0x02000000 + len(compdata))
    with common.Stream(outfile, "wb") as f:
        f.write(compdata)
