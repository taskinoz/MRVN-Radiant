// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
#pragma once
#include "box_coverage.h"
#include <cmath>
#include <limits>
#include <stdexcept>

namespace Respawn {
struct CoveragePlane { std::array<double,3> normal; double distance; };
// The bounds participate in the solid. Planes impose any additional cuts.
struct CoverageSolid { CoverageBox bounds; std::vector<CoveragePlane> planes; };

namespace CoverageDetail {
using Point = std::array<double,3>;
using Face = std::vector<Point>;
using Polyhedron = std::vector<Face>;
inline Point subtract(const Point& a,const Point& b) { return {a[0]-b[0],a[1]-b[1],a[2]-b[2]}; }
inline double dot(const Point& a,const Point& b) { return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]; }
inline Point cross(const Point& a,const Point& b) { return {a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]}; }
inline Polyhedron box(const CoverageBox& b) {
    const Point p[8]={{b.mins[0],b.mins[1],b.mins[2]},{b.maxs[0],b.mins[1],b.mins[2]},
                      {b.maxs[0],b.maxs[1],b.mins[2]},{b.mins[0],b.maxs[1],b.mins[2]},
                      {b.mins[0],b.mins[1],b.maxs[2]},{b.maxs[0],b.mins[1],b.maxs[2]},
                      {b.maxs[0],b.maxs[1],b.maxs[2]},{b.mins[0],b.maxs[1],b.maxs[2]}};
    return {{p[0],p[3],p[2],p[1]},{p[4],p[5],p[6],p[7]},
            {p[0],p[1],p[5],p[4]},{p[1],p[2],p[6],p[5]},
            {p[2],p[3],p[7],p[6]},{p[3],p[0],p[4],p[7]}};
}
inline double volume(const Polyhedron& p) {
    Point origin{}; std::size_t count=0;
    for (const auto& f:p) for (const auto& v:f) { for(int a=0;a<3;++a) origin[a]+=v[a]; ++count; }
    if (!count) return 0;
    for(auto& v:origin) v/=count;
    double result=0;
    for(const auto& f:p) for(std::size_t i=2;i<f.size();++i)
        result+=std::abs(dot(subtract(f[0],origin),cross(subtract(f[i-1],origin),subtract(f[i],origin))))/6;
    return result;
}
inline bool overlap(const Polyhedron& p,const CoverageBox& b) {
    if(p.empty()) return false;
    Point low={INFINITY,INFINITY,INFINITY},high={-INFINITY,-INFINITY,-INFINITY};
    for(const auto& f:p) for(const auto& v:f) for(int a=0;a<3;++a) {
        low[a]=std::min(low[a],v[a]); high[a]=std::max(high[a],v[a]);
    }
    for(int a=0;a<3;++a) if(high[a]<=b.mins[a] || low[a]>=b.maxs[a]) return false;
    return true;
}
inline Polyhedron clip(const Polyhedron& input,const CoveragePlane& plane) {
    Polyhedron output; Face cap;
    bool inside=false,outside=false;
    for(const auto& f:input) for(const auto& v:f) {
        const double d=dot(plane.normal,v)-plane.distance;
        inside |= d<=0; outside |= d>0;
    }
    if(!outside) return input;
    if(!inside) return {};
    for(const auto& f:input) {
        Face clipped;
        for(std::size_t i=0;i<f.size();++i) {
            const auto& a=f[i]; const auto& b=f[(i+1)%f.size()];
            const double da=dot(plane.normal,a)-plane.distance,db=dot(plane.normal,b)-plane.distance;
            if(da<=0) clipped.push_back(a);
            if((da<=0)!=(db<=0)) {
                const double t=da/(da-db); Point v;
                for(int axis=0;axis<3;++axis) v[axis]=a[axis]+t*(b[axis]-a[axis]);
                clipped.push_back(v);
                bool duplicate=false;
                for(const auto& other:cap) {const auto delta=subtract(v,other); if(dot(delta,delta)<1e-18) {duplicate=true;break;}}
                if(!duplicate) cap.push_back(v);
            }
        }
        if(clipped.size()>=3) output.push_back(std::move(clipped));
    }
    if(cap.size()>=3) {
        Point center{};
        for(const auto& p:cap) for(int a=0;a<3;++a) center[a]+=p[a]/cap.size();
        // All cap vertices lie on the cutting plane. Sort in a stable local
        // basis; the volume calculation does not depend on face orientation.
        const Point seed=std::abs(plane.normal[0])<.8 ? Point{1,0,0} : Point{0,1,0};
        const Point u=cross(plane.normal,seed),v=cross(plane.normal,u);
        std::sort(cap.begin(),cap.end(),[&](const Point& a,const Point& b) {
            const auto da=subtract(a,center),db=subtract(b,center);
            return std::atan2(dot(da,v),dot(da,u))<std::atan2(dot(db,v),dot(db,u));
        });
        output.push_back(std::move(cap));
    }
    return output;
}
}

// Measure the union of bounded convex solids inside a cell's bounds. Outside
// fragments remain disjoint as each solid is subtracted, so overlaps never
// count twice. Coordinates are translated to the cell before clipping.
inline bool coversConvexFraction(const CoverageBox& cell,const std::vector<CoverageSolid>& input,double fraction) {
    if(!std::isfinite(fraction) || fraction<0 || fraction>1) throw std::invalid_argument("Invalid water coverage fraction");
    double total=1; CoverageBox local; const auto origin=cell.mins;
    for(int a=0;a<3;++a) {
        if(!std::isfinite(cell.mins[a]) || !std::isfinite(cell.maxs[a]) || !(cell.maxs[a]>cell.mins[a])) return false;
        local.mins[a]=0;local.maxs[a]=cell.maxs[a]-cell.mins[a];total*=local.maxs[a];
    }
    if(!std::isfinite(total)) return false;
    if(fraction==0) return true;
    std::vector<CoverageBox> bounds; bool axial=true;
    for(const auto& solid:input) {bounds.push_back(solid.bounds);axial &= solid.planes.empty();}
    if(axial) return coversBoxFraction(cell,bounds,fraction);
    // The box union is a cheap upper bound, often rejecting a large dry cell.
    if(!coversBoxFraction(cell,bounds,fraction)) return false;
    std::vector<CoverageDetail::Polyhedron> dry{CoverageDetail::box(local)};
    double covered=0; const double required=total*fraction,tolerance=total*1e-10;
    for(const auto& solid:input) {
        CoverageBox bound; bool empty=false;
        for(int a=0;a<3;++a) {bound.mins[a]=std::max(cell.mins[a],solid.bounds.mins[a])-origin[a];bound.maxs[a]=std::min(cell.maxs[a],solid.bounds.maxs[a])-origin[a];empty |= bound.mins[a]>=bound.maxs[a];}
        if(empty) continue;
        std::vector<CoveragePlane> planes;
        for(int a=0;a<3;++a) for(int sign:{-1,1}) {CoveragePlane p{};p.normal[a]=sign;p.distance=sign<0 ? -bound.mins[a] : bound.maxs[a];planes.push_back(p);}
        for(auto p:solid.planes) {
            const double length=std::sqrt(CoverageDetail::dot(p.normal,p.normal));
            if(!(length>0) || !std::isfinite(length) || !std::isfinite(p.distance)) throw std::invalid_argument("Invalid water coverage plane");
            p.distance-=CoverageDetail::dot(p.normal,origin);
            for(auto& n:p.normal) n/=length;
            p.distance/=length;planes.push_back(p);
        }
        std::vector<CoverageDetail::Polyhedron> next;
        for(const auto& piece:dry) {
            if(!CoverageDetail::overlap(piece,bound)) {next.push_back(piece);continue;}
            auto remainder=piece;
            for(const auto& plane:planes) {
                auto reverse=plane;for(auto& n:reverse.normal)n=-n;reverse.distance=-reverse.distance;
                auto outside=CoverageDetail::clip(remainder,reverse);
                if(CoverageDetail::volume(outside)>0) next.push_back(std::move(outside));
                remainder=CoverageDetail::clip(remainder,plane);
                if(remainder.empty()) break;
            }
            covered+=CoverageDetail::volume(remainder);
            if(covered+tolerance>=required) return true;
        }
        dry=std::move(next);
    }
    return false;
}
} // namespace Respawn
