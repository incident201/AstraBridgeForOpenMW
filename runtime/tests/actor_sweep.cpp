// Isolated Bullet world; all movement filtering comes from the production header.
// Build against runtime/native/astraactorsweep.hpp and the builder's Bullet ABI.
#include "astraactorsweep.hpp"
#include <btBulletCollisionCommon.h>
#include <cmath>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>

namespace
{
    constexpr int World=1, Door=2, Actor=4, HeightMap=8, Projectile=16;
    constexpr int Physical=World|Door|Actor|HeightMap|Projectile;

    void require(bool value,const char* name)
    {
        if (!value) throw std::runtime_error(name);
    }

    struct Scene
    {
        btDefaultCollisionConfiguration config;
        btCollisionDispatcher dispatcher{&config};
        btDbvtBroadphase broadphase;
        btCollisionWorld world{&dispatcher,&broadphase,&config};
        std::vector<std::unique_ptr<btCollisionShape>> shapes;
        std::vector<std::unique_ptr<btCollisionObject>> bodies;

        ~Scene()
        {
            for (auto& body:bodies) world.removeCollisionObject(body.get());
        }

        btCollisionObject* add(std::unique_ptr<btCollisionShape> shape,
            const btVector3& center,int group=World)
        {
            shape->setMargin(0);
            auto body=std::make_unique<btCollisionObject>();
            body->setCollisionShape(shape.get());
            body->setWorldTransform(btTransform(btQuaternion::getIdentity(),center));
            auto* result=body.get();
            shapes.push_back(std::move(shape));
            bodies.push_back(std::move(body));
            world.addCollisionObject(result,group,Physical);
            return result;
        }

        btCollisionObject* box(const btVector3& half,const btVector3& center,int group=World)
        {
            return add(std::make_unique<btBoxShape>(half),center,group);
        }
    };

    MWPhysics::AstraActorSweepCallback callback(const btCollisionObject* self,
        const btVector3& from,const btVector3& to)
    {
        MWPhysics::AstraActorSweepCallback out(self,from,to,Projectile);
        out.m_collisionFilterGroup=Actor;
        out.m_collisionFilterMask=Physical;
        return out;
    }

    void sweep(Scene& scene,const btCollisionObject* self,const btVector3& from,
        const btVector3& to,MWPhysics::AstraActorSweepCallback& result)
    {
        btTransform start=self->getWorldTransform(),end=start;
        start.setOrigin(from);end.setOrigin(to);
        scene.world.convexSweepTest(static_cast<const btConvexShape*>(self->getCollisionShape()),
            start,end,result);
    }

    void selfIgnored()
    {
        Scene scene;
        const btVector3 from(0,0,64),to(0,100,64);
        auto* self=scene.box(btVector3(16,16,64),from,Actor);
        auto result=callback(self,from,to);
        sweep(scene,self,from,to,result);
        require(!result.hasHit(),"self collision must be excluded");
        std::cout<<"self ignored\n";
    }

    void separatingContactKeepsLaterWall()
    {
        Scene scene;
        const btVector3 from(0,0,64),to(0,100,64);
        auto* self=scene.box(btVector3(16,16,64),from,Actor);
        auto* behind=scene.box(btVector3(80,10,80),btVector3(0,-25,64));
        auto* ahead=scene.box(btVector3(80,5,80),btVector3(0,80,64),Door);
        scene.box(btVector3(30,5,80),btVector3(0,35,64),Projectile);
        auto result=callback(self,from,to);
        // Force the documented initial contact before asking Bullet for the
        // rest of the sweep, so this checks the callback even on Bullet builds
        // that do not report initial overlap during convexSweepTest.
        btCollisionWorld::LocalConvexResult initial(behind,nullptr,btVector3(0,1,0),
            btVector3(0,-15,64),0);
        result.addSingleResult(initial,true);
        require(!result.hasHit() && result.m_closestHitFraction==1,
            "a separating initial result must not lower the closest fraction");
        sweep(scene,self,from,to,result);
        require(result.hasHit() && result.m_hitCollisionObject==ahead,
            "the later door must remain visible after ignored contact and projectile");
        require(result.m_closestHitFraction>0 && result.m_closestHitFraction<1,
            "a farther approaching collision needs a nonzero sweep fraction");
        std::cout<<"initial separating contact skipped; later door retained; projectile ignored\n";
    }

    void LowActorBodyDetected()
    {
        Scene scene;
        const btVector3 from(0,0,64),to(0,100,64);
        auto* self=scene.box(btVector3(16,16,64),from,Actor);
        auto* creature=scene.box(btVector3(12,12,20),btVector3(0,60,21),Actor);
        btCollisionWorld::ClosestRayResultCallback ray(btVector3(0,17,79),btVector3(0,100,79));
        ray.m_collisionFilterGroup=Actor;ray.m_collisionFilterMask=Physical;
        scene.world.rayTest(ray.m_rayFromWorld,ray.m_rayToWorld,ray);
        require(!ray.hasHit(),"the middle body ray should miss this short actor");
        auto result=callback(self,from,to);
        sweep(scene,self,from,to,result);
        require(result.hasHit() && result.m_hitCollisionObject==creature,
            "the actual body sweep must detect an actor below the middle ray");
        std::cout<<"short actor body detected despite clear middle ray\n";
    }

    void floorAndSlopeTangencyClear()
    {
        for (bool slope:{false,true})
        {
            Scene scene;
            const btScalar q=btScalar(1/std::sqrt(2.0));
            const btVector3 normal=slope?btVector3(0,-q,q):btVector3(0,0,1);
            const btVector3 from(0,0,64),to=slope?btVector3(0,100,164):btVector3(0,100,64);
            auto* self=scene.box(btVector3(16,16,64),from,Actor);
            auto* support=scene.add(std::make_unique<btStaticPlaneShape>(normal,0),
                btVector3(0,0,0),HeightMap);
            auto result=callback(self,from,to);
            btCollisionWorld::LocalConvexResult touching(support,nullptr,normal,btVector3(0,0,0),0);
            result.addSingleResult(touching,true);
            require(!result.hasHit(),"tangent support must not consume the closest fraction");
            sweep(scene,self,from,to,result);
            require(!result.hasHit(),"movement along flat or 45 degree support should remain clear");
        }
        std::cout<<"flat and 45 degree support tangency clear\n";
    }

    void localNormalTransformed()
    {
        Scene scene;
        const btVector3 from(0,0,64),to(0,100,64);
        auto* self=scene.box(btVector3(16,16,64),from,Actor);
        auto* wall=scene.box(btVector3(10,10,80),btVector3(0,80,64));
        auto transform=wall->getWorldTransform();
        transform.setRotation(btQuaternion(btVector3(0,0,1),SIMD_HALF_PI));
        wall->setWorldTransform(transform);
        auto result=callback(self,from,to);
        btCollisionWorld::LocalConvexResult separating(wall,nullptr,btVector3(1,0,0),
            btVector3(0,80,64),btScalar(.5));
        result.addSingleResult(separating,false);
        require(!result.hasHit(),"a rotated local normal must be tested in world space");
        btCollisionWorld::LocalConvexResult blocking(wall,nullptr,btVector3(-1,0,0),
            btVector3(0,80,64),btScalar(.5));
        result.addSingleResult(blocking,false);
        require(result.hasHit() && result.m_hitCollisionObject==wall,
            "the rotated approaching local normal must still block");
        std::cout<<"local contact normals transformed before direction filtering\n";
    }

    void rawSweepDoesNotImplementStepping()
    {
        Scene scene;
        const btVector3 from(0,0,64),to(0,140,76);
        auto* self=scene.box(btVector3(16,16,64),from,Actor);
        auto* step=scene.box(btVector3(100,50,6),btVector3(0,100,6));
        auto result=callback(self,from,to);
        sweep(scene,self,from,to,result);
        require(result.hasHit() && result.m_hitCollisionObject==step,
            "a raw body cast must expose its 12 unit stair-riser collision");
        // A stock step attempt additionally raises the body before advancing;
        // this fixture establishes why the callback alone cannot replace it.
        const btVector3 raisedFrom(0,0,77),raisedTo(0,140,77);
        auto raised=callback(self,raisedFrom,raisedTo);
        sweep(scene,self,raisedFrom,raisedTo,raised);
        require(!raised.hasHit(),"a raised body clears the same low stair riser");
        std::cout<<"raw riser collision exposed; raised traversal clear (stock step policy still required)\n";
    }

    void standingHeightUsesFootprint()
    {
        Scene scene;
        const btScalar q=btScalar(1/std::sqrt(2.0));
        auto* self=scene.box(btVector3(btScalar(29.28),btScalar(28.48),btScalar(66.5)),
            btVector3(0,0,btScalar(66.5)),Actor);
        auto* plane=scene.add(std::make_unique<btStaticPlaneShape>(btVector3(0,-q,q),0),
            btVector3(0,0,0),HeightMap);
        const btVector3 floor(0,100,100);
        const btVector3 centerOffset(0,0,btScalar(66.5));
        const btVector3 high=floor+btVector3(0,0,34),low=floor-btVector3(0,0,2);
        auto result=callback(self,high+centerOffset,low+centerOffset);
        sweep(scene,self,high+centerOffset,low+centerOffset,result);
        require(result.hasHit() && result.m_hitCollisionObject==plane,
            "the downward body probe must find walkable slope support");
        const btVector3 standing=high+(low-high)*result.m_closestHitFraction+btVector3(0,0,1);
        const btScalar offset=standing.z()-floor.z();
        require(result.m_hitNormalWorld.z()>std::cos(46*SIMD_PI/180),
            "45 degree support is within the engine walking slope limit");
        require(offset>25 && offset<35,
            "a valid standing footprint can exceed 25 units above the center floor ray");
        std::cout<<"45 degree standing offset "<<offset
            <<" exceeds 25 unit floor-point guard; remains within 35 unit arrival height\n";
    }
}

int main()
{
    try
    {
        selfIgnored();separatingContactKeepsLaterWall();LowActorBodyDetected();
        floorAndSlopeTangencyClear();localNormalTransformed();rawSweepDoesNotImplementStepping();
        standingHeightUsesFootprint();
        std::cout<<"actor sweep callback contracts passed\n";
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr<<"actor sweep contract failed: "<<error.what()<<'\n';
        return 1;
    }
}
