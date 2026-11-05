// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
#include "../remap/source/respawn/encoding.h"
#include "../remap/source/respawn/tricoll_bevels.h"
#include "../remap/source/respawn/tricoll_partition.h"
#include "../remap/source/respawn/convex_cells.h"
#include "../remap/source/respawn/convex_brushes.h"
#include "../remap/source/respawn/box_coverage.h"
#include "../remap/source/respawn/convex_coverage.h"
#include "../remap/source/respawn/vmt_surfaceprop.h"
#include "../remap/source/respawn/tricoll_bevel_select.h"
#include "../remap/source/respawn/tricoll_bevel_select.h"
#include <iostream>
#include <limits>
#include <map>

static void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
template<class F> static void rejects(F function) {
    bool rejected = false;
    try { function(); } catch (const std::exception&) { rejected = true; }
    require(rejected, "Expected invalid encoding input to be rejected");
}

int main() {
    try {
        // Literal wire packets also cover indices straddling a 32-bit word.
        for (unsigned width : {10u, 11u}) {
            using Ref = Respawn::TricollBevelReference;
            const auto unpack = [width](const Respawn::TricollBevelEncoding& packet, std::size_t index) {
                const auto bit = index * width;
                std::uint64_t value = packet.words[bit / 32];
                if (bit / 32 + 1 < packet.words.size()) value |= std::uint64_t(packet.words[bit / 32 + 1]) << 32;
                return std::uint32_t((value >> (bit % 32)) & ((1u << width) - 1));
            };
            const auto empty = Respawn::encodeTricollBevels(width, 0, {2}, {{}, {}});
            require(empty.indexCount == 0 && empty.words.empty() && empty.starts == std::vector<std::uint16_t>{0,0}
                    && empty.counts == std::vector<std::uint8_t>{0,0}, "Empty bevel packet has no words");
            const auto direct = Respawn::encodeTricollBevels(width, 0, {std::uint16_t(1u << width)}, [&] {
                std::vector<std::vector<Ref>> refs(1u << width);
                refs[0] = {{0,3},{0,7},{0,(1u << width)-1},{0,9}};
                return refs;
            }());
            require(direct.counts[0] == 4 && direct.indexCount == 4 && direct.words.size() == 2
                    && unpack(direct,0) == 3 && unpack(direct,1) == 7
                    && unpack(direct,2) == (1u << width)-1 && unpack(direct,3) == 9,
                    "Direct local bevel values preserve both format widths");
            const auto cross = Respawn::encodeTricollBevels(width, 0, {2,3}, {{{0,1},{1,2}}, {}});
            const std::vector<std::uint32_t> literal{129,0,2,1,0,1};
            require(cross.counts[0] == 15 && cross.indexCount == literal.size(), "Cross-header lists require chains");
            for (std::size_t i=0;i<literal.size();++i)
                require(unpack(cross,i) == literal[i], "Foreign header precedes the terminating local segment");
            const auto foreign = Respawn::encodeTricollBevels(width, 0, {1,256}, [&] {
                std::vector<std::vector<Ref>> refs(1);
                for (unsigned i=0;i<256;++i) refs[0].push_back({1,i});
                return refs;
            }());
            require(foreign.indexCount == 264 && unpack(foreign,0) == 255 && unpack(foreign,129) == 255
                    && unpack(foreign,258) == 130 && unpack(foreign,262) == 0 && unpack(foreign,263) == 0,
                    "Foreign groups split at 127 references and terminate with zero count");
            const auto fifteen = Respawn::encodeTricollBevels(width, 0, {15}, [&] {
                std::vector<std::vector<Ref>> refs(15);
                for (unsigned i=0;i<15;++i) refs[0].push_back({0,i});
                return refs;
            }());
            require(fifteen.counts[0] == 15 && fifteen.indexCount == 17 && unpack(fifteen,0) == 15
                    && unpack(fifteen,1) == 0 && unpack(fifteen,16) == 14,
                    "Fifteen local references encode a terminating local chain");
            const std::uint32_t maxHeader = (1u << (width*2-7))-1;
            std::vector<std::uint16_t> headers(maxHeader+2,1);
            const auto lastHeader = Respawn::encodeTricollBevels(width,0,headers,{{{maxHeader,0}}});
            require(unpack(lastHeader,0) == (((maxHeader<<7)|1)&((1u<<width)-1))
                    && unpack(lastHeader,1) == (((maxHeader<<7)|1)>>width),
                    "Highest encodable chain header preserves its high bits");
            rejects([&]{ Respawn::encodeTricollBevels(width,0,headers,{{{maxHeader+1,0}}}); });
            rejects([&]{ Respawn::encodeTricollBevels(width,maxHeader+1,headers,{{{0,0}}}); });
            const auto foreignOnly = Respawn::encodeTricollBevels(width,1,{1,1},{{{0,0}}});
            require(foreignOnly.indexCount == 5 && unpack(foreignOnly,3) == 128 && unpack(foreignOnly,4) == 0,
                    "A zero-count terminator must name the current header");
            require(Respawn::encodeTricollBevels(width,maxHeader+1,headers,{{{maxHeader+1,0}}}).counts[0] == 1,
                    "Direct references do not truncate a large current header number");
            const auto local127 = Respawn::encodeTricollBevels(width,0,{127},[&] {
                std::vector<std::vector<Ref>> refs(127);
                for (unsigned i=0;i<127;++i) refs[0].push_back({0,i});
                return refs;
            }());
            require(local127.indexCount == 129 && unpack(local127,0) == 127 && unpack(local127,128) == 126,
                    "A terminating local segment supports exactly 127 references");
            rejects([&]{ Respawn::encodeTricollBevels(width,maxHeader+1,headers,{{{0,0},{maxHeader+1,0}}}); });
            rejects([&]{ Respawn::encodeTricollBevels(width,0,{128},[&] {
                std::vector<std::vector<Ref>> refs(128);
                for (unsigned i=0;i<128;++i) refs[0].push_back({0,i});
                return refs;
            }()); });
            rejects([&]{ Respawn::encodeTricollBevels(width,0,{1},{{{1,0}}}); });
            rejects([&]{ Respawn::encodeTricollBevels(width,0,{1},{{{0,1}}}); });
            rejects([&]{ Respawn::encodeTricollBevels(width,0,{1},{}); });
            rejects([&]{ Respawn::encodeTricollBevels(width,0,{0},{}); });
        }
        {
            using Ref = Respawn::TricollBevelReference;
            std::vector<std::vector<Ref>> refs(3);
            refs[0].assign(64516, {1,0}); refs[1] = {{0,0}};
            const auto full = Respawn::encodeTricollBevels(10,0,{3,1},refs);
            require(full.indexCount == 65535 && full.starts[1] == 65534 && full.starts[2] == 0,
                    "Full 16-bit bevel stream retains its final offset and empty-list sentinel");
            refs[1].push_back({0,1});
            rejects([&]{ Respawn::encodeTricollBevels(10,0,{3,1},refs); });
            std::vector<std::vector<Ref>> wide(1);
            wide[0] = {{1,1024}};
            rejects([&]{ Respawn::encodeTricollBevels(10,0,{1,1025},wide); });
            require(Respawn::encodeTricollBevels(11,0,{1,1025},wide).indexCount == 5,
                    "TF2 may reference triangle indices beyond TF1's ten-bit limit");
        }
        rejects([]{ Respawn::encodeTricollBevels(9,0,{1},{{}}); });
        // Decode planned headers independently and recover entity-wide IDs.
        // This checks that repartitioning preserves every reference, including
        // references crossing material batches and splits of a target header.
        const auto verifyPartition = [](unsigned width, const std::vector<std::uint32_t>& sizes,
                                        const std::vector<std::vector<std::uint32_t>>& refs,
                                        std::size_t preceding = 0) {
            const auto chunks = Respawn::partitionTricollBevels(width,
                std::vector<std::uint16_t>(preceding,1),sizes,refs);
            std::vector<std::uint32_t> offsets{0};
            for (const auto size : sizes) offsets.push_back(offsets.back()+size);
            std::uint32_t seen = 0;
            for (std::size_t h=0;h<chunks.size();++h) {
                const auto& c=chunks[h]; const auto& packet=c.bevels;
                require(c.firstTriangle == seen && c.triangleCount && c.triangleCount <= 300,
                        "Partition retains every triangle in its original order");
                require(c.firstTriangle >= offsets[c.batch] && c.firstTriangle+c.triangleCount <= offsets[c.batch+1],
                        "Partition cannot mix material/contents batches");
                seen += c.triangleCount;
                const auto read = [&](std::size_t at) {
                    require(at<packet.indexCount,"Decoded partition stream is in bounds");
                    const auto bit=at*width;
                    std::uint64_t bits=packet.words[bit/32];
                    if (bit/32+1<packet.words.size()) bits|=std::uint64_t(packet.words[bit/32+1])<<32;
                    return std::uint32_t((bits>>(bit%32))&((1u<<width)-1));
                };
                for (unsigned i=0;i<c.triangleCount;++i) {
                    std::vector<std::uint32_t> actual;
                    std::size_t cursor=packet.starts[i];
                    auto amount=std::uint32_t(packet.counts[i]);
                    const bool chain=amount==15;
                    do {
                        std::size_t target=h;
                        if (chain) {
                            const auto low=read(cursor++),high=read(cursor++);
                            const auto descriptor=low|(high<<width);amount=descriptor&127;
                            require((descriptor>>7)>=preceding,"References remain inside the current entity");
                            target=(descriptor>>7)-preceding;
                        }
                        require(target<chunks.size(),"Decoded target header is in bounds");
                        for (unsigned k=0;k<amount;++k) {
                            const auto local=read(cursor++);
                            require(local<chunks[target].triangleCount,"Decoded local target is in bounds");
                            actual.push_back(chunks[target].firstTriangle+local);
                        }
                        if (!chain || target==h) break;
                    } while (true);
                    auto expected=refs[c.firstTriangle+i];
                    std::sort(expected.begin(),expected.end());std::sort(actual.begin(),actual.end());
                    require(actual==expected,"Repartitioning cannot lose, add or retarget a plane reference");
                }
            }
            require(seen==refs.size(),"Partition covers the complete entity");
            return chunks.size();
        };
        for (unsigned width : {10u,11u}) {
            require(verifyPartition(width,{0,0},{})==0,"Empty batches emit no headers");
            require(verifyPartition(width,{301,2},std::vector<std::vector<std::uint32_t>>(303),7)==3,
                    "Empty plane lists retain the existing 300-triangle header cuts");
            std::vector<std::vector<std::uint32_t>> dense(300);
            for (unsigned i=0;i<300;++i) for (unsigned j=0;j<300;++j) if(i!=j) dense[i].push_back(j);
            require(verifyPartition(width,{300},dense,5)>1,
                    "High-valence local fans repartition before the 127-target limit");
            std::vector<std::vector<std::uint32_t>> stream(301);
            for (unsigned i=0;i<300;++i) stream[i].assign(220,300);
            require(verifyPartition(width,{300,1},stream)>2,
                    "A header's aggregate 16-bit stream overflow also forces repartitioning");
            std::vector<std::vector<std::uint32_t>> cascading(589);
            for (unsigned i=0;i<289;++i) for (unsigned j=289;j<509;++j) cascading[i].push_back(j);
            for (unsigned i=289;i<589;++i) for (unsigned j=289;j<589;++j) if(i!=j) cascading[i].push_back(j);
            require(verifyPartition(width,{289,300},cascading)>5,
                    "Splitting target headers can overflow an initially fitting foreign stream; revisit all headers");
            rejects([&]{ Respawn::partitionTricollBevels(width,{}, {1},{{1}}); });
            rejects([&]{ Respawn::partitionTricollBevels(width,{}, {2},{{}}); });
            rejects([&]{ Respawn::partitionTricollBevels(width,{}, {1},{{}},0); });
            rejects([&]{ Respawn::partitionTricollBevels(width,{}, {1},
                {std::vector<std::uint32_t>(128,0)}); });
            rejects([&]{ Respawn::partitionTricollBevels(width,{}, {1,1},
                {std::vector<std::uint32_t>(65534,1),{}}); });
            require(verifyPartition(width,{1},{{0}},65535)==1,
                    "The final native primitive header remains usable for direct lists");
            rejects([&]{ Respawn::partitionTricollBevels(width,std::vector<std::uint16_t>(65535,1),
                {2},{{},{}},1); });
            {
                // Past the chain header field, cross-header bevels are dropped (conservative).
                const auto beyond = Respawn::partitionTricollBevels(width,
                    std::vector<std::uint16_t>(1u<<(2*width-7),1),{1,1},{{1},{0}});
                require(beyond.size()==2 && beyond[0].droppedReferences==1 && beyond[1].droppedReferences==1,
                        "Chain targets past the header field are dropped, not encoded");
            }
        }
        Respawn::CellMergeGroups groups(6);
        groups.protect(0, 1);
        groups.protect(3, 4);
        require(!groups.join(0, 1), "Protected direct interface cannot merge");
        require(groups.join(2, 0), "Unprotected alternate path can merge");
        require(!groups.canJoin(1, 2) && !groups.join(2, 1),
                "Alternate path cannot erase a protected interface");
        require(groups.join(5, 4) && groups.join(3, 1), "Both protected owners can change");
        require(!groups.join(5, 3) && !groups.join(3, 5),
                "Exclusions survive ownership changes on both sides");
        require(groups.join(5, 2), "Unrelated protected regions can merge");
        require(!groups.join(3, 5), "Accumulated exclusions survive further merges");
        require(!groups.join(5, 5), "Already merged groups do not merge again");
        const std::string names("compat\\bump_extra\0compat\\bump\0", 30);
        const std::vector<char> pool(names.begin(), names.end());
        require(!Respawn::textureNameEquals(pool, 0, "compat\\bump"), "Prefix alias rejected");
        require(Respawn::textureNameEquals(pool, 18, "compat\\bump"), "Later exact match found");
        require(!Respawn::textureNameEquals(pool, std::numeric_limits<std::size_t>::max(), "x"), "Offset bounded");
        require(!Respawn::textureNameEquals({'a'}, 0, "a"), "Terminator required");
        require(Respawn::textureName("textures/compat/bump") == "compat\\bump", "Texture prefix normalization");
        require(Respawn::textureName("noshader") == "noshader", "Unprefixed short name preserved");
        rejects([] { Respawn::textureName("textures/"); });
        rejects([] { Respawn::textureName(std::string("x\0y", 3)); });
        const auto integer = Respawn::quantizeBoundsAxis(-64, 64);
        require(integer.origin == 0 && integer.extent == 66, "Existing integer collision margin preserved");
        for (int a = -64; a < 64; ++a) {
            for (int width = 0; width < 32; ++width) {
                const double minimum = a * 0.125;
                const double maximum = minimum + width * 0.125;
                const auto encoded = Respawn::quantizeBoundsAxis(minimum, maximum);
                require(encoded.origin - encoded.extent <= minimum - 2 &&
                        encoded.origin + encoded.extent >= maximum + 2,
                        "Fractional bounds contain both sides and their margin");
            }
        }
        rejects([] { Respawn::quantizeBoundsAxis(32767.5, 32768.5); });
        rejects([] { Respawn::quantizeBoundsAxis(-32768, 32767); });
        rejects([] { Respawn::quantizeBoundsAxis(1, -1); });
        rejects([] { Respawn::quantizeBoundsAxis(std::numeric_limits<double>::quiet_NaN(), 1); });
        rejects([] { Respawn::quantizeBoundsAxis(0, std::numeric_limits<double>::infinity()); });
        const std::pair<std::array<float, 3>, uint32_t> orders[] = {
            {{0, 0, 0}, 4}, {{0, 0, 1}, 4}, {{0, 1, 0}, 0}, {{1, 0, 0}, 1},
            {{0, 1, 1}, 4}, {{1, 0, 1}, 5}, {{1, 1, 0}, 2},
            {{0, 1, 2}, 4}, {{0, 2, 1}, 0}, {{1, 0, 2}, 5},
            {{2, 0, 1}, 1}, {{1, 2, 0}, 2}, {{2, 1, 0}, 6}
        };
        for (const auto& order : orders)
            require(Respawn::triangleZOrder(order.first) == order.second,
                    "Triangle height ordering preserves retail tie rules");
        const auto cellBox = [](double lx, double ly, double hx, double hy) {
            Respawn::ConvexCellHull hull;
            hull.planes = {{{-1,0,0},-lx}, {{1,0,0},hx}, {{0,-1,0},-ly},
                           {{0,1,0},hy}, {{0,0,-1},0}, {{0,0,1},1}};
            for (double x : {lx,hx}) for (double y : {ly,hy}) for (double z : {0.,1.})
                hull.points.push_back({x,y,z});
            return hull;
        };
        auto cellA = cellBox(0,0,1,1);
        const auto cellB = cellBox(1,0,2,1);
        require(Respawn::canMergeBrushHulls(cellA,1,cellB,0), "Collision removes an internal full-face plane");
        require(!Respawn::canMergeBrushHulls(cellA,1,cellBox(1,0,2,0.5),0),
                "Collision may not fill a concavity at a partial face");
        require(!Respawn::canMergeBrushHulls(cellA,1,cellBox(1.00001,0,2,1),0),
                "Collision may not close an authored gap");
        require(!Respawn::canMergeBrushHulls(cellA,1,cellBox(0.99999,0,2,1),0),
                "Overlapping volumes are not an exact face join");
        require(!Respawn::canMergeBrushHulls(cellA,0,cellB,0), "Same-facing planes cannot join");
        require(!Respawn::canMergeBrushHulls(cellA,6,cellB,0), "Missing interfaces cannot join");
        auto emptyBrush = cellB; emptyBrush.points.clear();
        require(!Respawn::canMergeBrushHulls(cellA,1,emptyBrush,0), "Empty brush cannot join");
        const Respawn::CellPlane separator{{1,0,0},1};
        require(Respawn::canMergeCells(cellA, cellB, separator), "Adjacent boxes form one convex cell");
        require(!Respawn::canMergeCells(cellA, cellBox(1,0,2,0.5), separator),
                "Partial face creates a concave union and must retain its portal");
        require(!Respawn::canMergeCells(cellA, cellBox(2,0,3,1), separator),
                "Separated boxes cannot merge");
        Respawn::mergeCells(cellA, cellB, separator);
        require(cellA.planes.size() == 6, "Merged box retains its six exterior planes");
        require(Respawn::canMergeCells(cellA, cellBox(2,0,3,1), {{1,0,0},2}),
                "Convex merges can continue across original leaf boundaries");
        require(!Respawn::canMergeCells(cellA, cellBox(0,1,1,2), {{0,1,0},1}),
                "An L-shaped room keeps distinct cells after earlier merges");
        std::string prop;
        require(Respawn::vmtSurfaceProp("LightmappedGeneric { $surfaceprop metal }", prop) && prop == "metal",
                "Unquoted VMT property and value");
        require(Respawn::vmtSurfaceProp("\xef\xbb\xbf\"Shader\" { // \"$surfaceprop\" \"wrong\"\n"
                                        "/* $surfaceprop wrong */ \"$SurfaceProp\" wood }", prop) && prop == "wood",
                "VMT BOM, comments, quoted keys and case");
        require(Respawn::vmtSurfaceProp("Shader { key \"$surfaceprop\" nested { x \"}\" } $surfaceprop glass }", prop) && prop == "glass",
                "VMT values and quoted braces are not keys or syntax");
        prop = "default";
        require(!Respawn::vmtSurfaceProp("Shader { /* unterminated $surfaceprop metal", prop) && prop == "default",
                "Malformed VMT does not invent a property");
        const std::map<std::string, std::string> vmts = {
            {"materials/base.vmt", "Shader { $surfaceprop metal }"},
            {"materials/empty.vmt", "Shader { Proxies { test { $surfaceprop wrong } } }"},
            {"materials/inherit.vmt", "Patch { include materials/base.vmt }"},
            {"materials/insert.vmt", "Patch { include materials/empty.vmt insert { $surfaceprop sand } }"},
            {"materials/replace.vmt", "Patch { include materials/inherit.vmt replace { $surfaceprop wood } }"},
            {"materials/no-replace.vmt", "Patch { include materials/empty.vmt replace { $surfaceprop wrong } }"},
            {"materials/cycle.vmt", "Patch { include materials/cycle.vmt insert { $surfaceprop wrong } }"},
            {"materials/escape.vmt", "Patch { include materials/../secret.vmt insert { $surfaceprop wrong } }"},
        };
        auto loadVmt = [&](const std::string &path, std::string &text) {
            auto item = vmts.find(path);
            if (item == vmts.end()) return false;
            text = item->second;
            return true;
        };
        Respawn::VmtProperty resolved;
        require(Respawn::resolveVmtSurfaceProp("materials/inherit.vmt", loadVmt, resolved) && resolved.value == "metal",
                "Patch inherits base property");
        require(Respawn::resolveVmtSurfaceProp("materials/insert.vmt", loadVmt, resolved) && resolved.value == "sand",
                "Patch insert creates property");
        require(Respawn::resolveVmtSurfaceProp("materials/replace.vmt", loadVmt, resolved) && resolved.value == "wood",
                "Patch chain replaces inherited property");
        require(Respawn::resolveVmtSurfaceProp("materials/no-replace.vmt", loadVmt, resolved) && !resolved.present,
                "Patch replace does not create missing property");
        require(!Respawn::resolveVmtSurfaceProp("materials/cycle.vmt", loadVmt, resolved), "Patch cycle rejected");
        require(!Respawn::resolveVmtSurfaceProp("materials/escape.vmt", loadVmt, resolved), "Patch traversal rejected");
        require(!Respawn::resolveVmtSurfaceProp("materials/missing.vmt", loadVmt, resolved), "Missing VMT rejected");
        const Respawn::CoverageBox cell{{0, 0, 0}, {10, 10, 10}};
        require(!Respawn::coversBoxFraction(cell, {{{0, 0, 0}, {2, 10, 10}}, {{8, 0, 0}, {10, 10, 10}}}, 0.5),
                "Separate pools do not fill their enclosing bounds");
        require(Respawn::coversBoxFraction(cell, {{{0, 0, 0}, {2.5, 10, 10}}, {{2.5, 0, 0}, {5, 10, 10}}}, 0.5),
                "Adjacent brushes cover half a cell together");
        require(!Respawn::coversBoxFraction(cell, {{{0, 0, 0}, {3, 10, 10}}, {{0, 0, 0}, {3, 10, 10}}}, 0.5),
                "Overlapping brushes are not counted twice");
        require(Respawn::coversBoxFraction(cell, {{{0, 0, 0}, {3, 10, 10}}, {{2, 0, 0}, {5, 10, 10}}}, 0.5),
                "Partial overlap contributes its union only");
        const Respawn::CoverageBox unit{{0,0,0},{1,1,1}};
        const Respawn::CoverageSolid wedge{unit,{{{1,1,0},1}}};
        const Respawn::CoverageSolid reverseWedge{unit,{{{-1,-1,0},-1}}};
        require(Respawn::coversConvexFraction(unit,{wedge},.5), "Triangular water prism covers exactly half a cell");
        require(!Respawn::coversConvexFraction(unit,{wedge},.50001), "Water prism excludes the dry half of its bounds");
        require(!Respawn::coversConvexFraction({{.75,.75,0},{1,1,1}},{wedge},.5), "Dry corner inside water bounds stays dry");
        require(Respawn::coversConvexFraction({{0,0,0},{.25,.25,1}},{wedge},1), "Submerged corner is wholly covered");
        require(!Respawn::coversConvexFraction(unit,{wedge,wedge},.75), "Overlapping sloped water is counted once");
        require(Respawn::coversConvexFraction(unit,{wedge,reverseWedge},1), "Complementary sloped volumes cover the cell");
        const Respawn::CoverageSolid largerWedge{unit,{{{1,1,0},1.5}}};
        require(Respawn::coversConvexFraction(unit,{wedge,largerWedge},.875), "Nested sloped union has its analytic volume");
        require(!Respawn::coversConvexFraction(unit,{wedge,largerWedge},.876), "Nested sloped union does not double count");
        const Respawn::CoverageSolid tetrahedron{unit,{{{1,1,1},1}}};
        require(Respawn::coversConvexFraction(unit,{tetrahedron},1./6), "Three-dimensional diagonal clipping has tetrahedron volume");
        require(!Respawn::coversConvexFraction(unit,{tetrahedron},.167), "Tetrahedron does not fill its enclosing box");
        const Respawn::CoverageSolid ramp{unit,{{{-1,0,1},0}}};
        const Respawn::CoverageSolid reverseRamp{unit,{{{1,0,-1},0}}};
        require(Respawn::coversConvexFraction(unit,{ramp,reverseRamp},1), "Opposed ramps cover the full cell");
        const Respawn::CoverageSolid boxPart{{{0,0,0},{.5,1,1}}, {}};
        require(Respawn::coversConvexFraction(unit,{boxPart,reverseWedge},.875), "Axial and sloped volumes form the analytic union");
        require(!Respawn::coversConvexFraction(unit,{boxPart,reverseWedge},.876), "Mixed union excludes its dry triangular region");
        const Respawn::CoverageBox translated{{1000000,-2000000,3000000},{1000001,-1999999,3000001}};
        const Respawn::CoverageSolid translatedWedge{translated,{{{2,2,0},-1999998}}};
        require(Respawn::coversConvexFraction(translated,{translatedWedge},.5), "Translated non-unit normals retain half coverage");
        require(!Respawn::coversConvexFraction(translated,{translatedWedge},.50001), "World translation does not create water volume");
        require(!Respawn::coversConvexFraction(unit,{{{{2,2,2},{3,3,3}},{{{1,1,0},5}}}},.1), "Disjoint water volumes do not cover the cell");
        require(!Respawn::coversConvexFraction(unit,std::vector<Respawn::CoverageSolid>(100,wedge),.75), "Repeated volumes preserve union coverage");
        {
            // Front normals are cross(v2 - v0, v1 - v0). Ridge faces select each
            // other, valley faces never do, and unshared triangles are ignored.
            using T = Respawn::BevelTriangle;
            const T a{{{{0, 0, 0}}, {{-64, 0, -64}}, {{0, 64, 0}}}};  // faces (-x, +z)
            const T b{{{{0, 0, 0}}, {{0, 64, 0}}, {{64, 0, -64}}}};   // faces (+x, +z)
            const auto ridge = Respawn::selectTricollBevels({a, b});
            require(ridge[0] == std::vector<std::uint32_t>{1} && ridge[1] == std::vector<std::uint32_t>{0},
                    "Convex ridge faces select each other");
            const T c{{{{0, 0, 0}}, {{-64, 0, 64}}, {{0, 64, 0}}}};   // faces (+x, +z)
            const T d{{{{0, 0, 0}}, {{0, 64, 0}}, {{64, 0, 64}}}};    // faces (-x, +z)
            const auto valley = Respawn::selectTricollBevels({c, d});
            require(valley[0].empty() && valley[1].empty(), "Concave valley faces select nothing");
            const T far{{{{1000, 0, 0}}, {{1000, 64, 0}}, {{1064, 0, -64}}}};
            require(Respawn::selectTricollBevels({a, far})[0].empty(), "Triangles without a shared vertex are not selected");
            const T down{{{{0, 0, 0}}, {{0, 64, 0}}, {{-64, 0, -64}}}};  // faces (+x, -z)
            require(Respawn::selectTricollBevels({down, b})[0].empty(), "Steeply downward sources select nothing");
            // TF1 chain segments name headers in 13 bits: past 8192, keep plain
            // local lists and drop foreign references instead of failing.
            const std::vector<std::uint16_t> preceding(8192, 1);
            const auto local = Respawn::partitionTricollBevels(10, preceding, {2}, {{1}, {0}});
            require(local.size() == 1 && local[0].droppedReferences == 0 && local[0].bevels.indexCount == 2,
                    "Headers past 8192 keep same-header lists");
            const auto foreign = Respawn::partitionTricollBevels(10, preceding, {2}, {{1}, {0}}, 1);
            require(foreign.size() == 2 && foreign[0].droppedReferences == 1 && foreign[1].droppedReferences == 1 &&
                    foreign[0].bevels.indexCount == 0, "Unencodable TF1 chain references are dropped");
            const auto wide = Respawn::partitionTricollBevels(11, preceding, {2}, {{1}, {0}}, 1);
            require(wide[0].droppedReferences == 0 && wide[0].bevels.indexCount > 0, "TF2's wider chain field keeps them");
        }
        std::cout << "Texture identity and conservative collision encoding tests passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
