#ifndef OPENMW_MWPHYSICS_ASTRAACTORSWEEP_H
#define OPENMW_MWPHYSICS_ASTRAACTORSWEEP_H

#include <BulletCollision/CollisionDispatch/btCollisionWorld.h>

namespace MWPhysics
{
    // Read-only counterpart of the movement tracer. Reject non-blocking
    // contacts before updating the closest fraction, so a touched floor or
    // separating initial overlap cannot hide a later wall. No projectile hit
    // callbacks, actor relocation, or pair-contact mutation are performed.
    class AstraActorSweepCallback final : public btCollisionWorld::ClosestConvexResultCallback
    {
    public:
        AstraActorSweepCallback(const btCollisionObject* self, const btVector3& fromCenter,
            const btVector3& toCenter, int projectileGroup)
            : btCollisionWorld::ClosestConvexResultCallback(fromCenter, toCenter)
            , mSelf(self)
            , mDirection(toCenter - fromCenter)
            , mProjectileGroup(projectileGroup)
        {
            if (mDirection.length2() > SIMD_EPSILON * SIMD_EPSILON)
                mDirection.normalize();
        }

        bool needsCollision(btBroadphaseProxy* proxy) const override
        {
            if (proxy->m_clientObject == mSelf || (proxy->m_collisionFilterGroup & mProjectileGroup) != 0)
                return false;
            return ClosestConvexResultCallback::needsCollision(proxy);
        }

        btScalar addSingleResult(btCollisionWorld::LocalConvexResult& result, bool normalInWorldSpace) override
        {
            const auto* object = result.m_hitCollisionObject;
            const auto* proxy = object->getBroadphaseHandle();
            if (object == mSelf || (proxy && (proxy->m_collisionFilterGroup & mProjectileGroup) != 0))
                return btScalar(1);

            btVector3 normal = result.m_hitNormalLocal;
            if (!normalInWorldSpace)
                normal = object->getWorldTransform().getBasis() * normal;
            if (normal.length2() <= SIMD_EPSILON * SIMD_EPSILON)
                return btScalar(1);
            normal.normalize();
            // Motion points from the hypothetical starting center to its goal.
            // Positive dot separates; zero slides along a touched surface.
            // A small angular epsilon only absorbs floating-point floor noise.
            if (mDirection.dot(normal) >= btScalar(-1e-5))
                return btScalar(1);

            return ClosestConvexResultCallback::addSingleResult(result, normalInWorldSpace);
        }

    private:
        const btCollisionObject* mSelf;
        btVector3 mDirection;
        int mProjectileGroup;
    };
}

#endif
