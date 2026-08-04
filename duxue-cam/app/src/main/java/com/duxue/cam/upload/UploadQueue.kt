package com.duxue.cam.upload

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase

@Entity(tableName = "pending_frames")
data class PendingFrame(@PrimaryKey(autoGenerate = true) val id: Long = 0, val filePath: String, val capturedAt: String, val elapsedRealtime: Long, val sizeBytes: Long)

@Dao interface FrameDao {
    @Insert suspend fun insert(frame: PendingFrame)
    @Query("SELECT * FROM pending_frames ORDER BY id LIMIT 1") suspend fun oldest(): PendingFrame?
    @Query("DELETE FROM pending_frames WHERE id = :id") suspend fun delete(id: Long)
    @Query("SELECT COUNT(*) FROM pending_frames") suspend fun count(): Int
    @Query("SELECT COALESCE(SUM(sizeBytes),0) FROM pending_frames") suspend fun bytes(): Long
}

@Database(entities = [PendingFrame::class], version = 1)
abstract class QueueDatabase : RoomDatabase() {
    abstract fun frames(): FrameDao
    companion object { fun open(context: Context) = Room.databaseBuilder(context, QueueDatabase::class.java, "capture-queue.db").build() }
}

class UploadQueue(private val dao: FrameDao) {
    suspend fun enqueue(frame: PendingFrame) {
        dao.insert(frame)
        while (QueuePolicy.isOverCapacity(dao.count(), dao.bytes())) {
            val oldest = dao.oldest() ?: break
            java.io.File(oldest.filePath).delete(); dao.delete(oldest.id)
        }
    }
    suspend fun peek() = dao.oldest()
    suspend fun remove(frame: PendingFrame) { java.io.File(frame.filePath).delete(); dao.delete(frame.id) }
    suspend fun size() = dao.count()
}
